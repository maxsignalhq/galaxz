# Goal Token Budget and Provider Failover — Design

Date: 2026-10-12 · Status: draft, decisions confirmed in chat, awaiting final review

Origin: comparison with paperclipai/paperclip, whose per-scope budgets with hard
stops are the one operational feature Galaxz has no equivalent for. Paperclip
documents pause/hard-stop only; model failover and timed resume below are
Galaxz's own design.

## Revision 2026-10-12 (after reading the execution path)

Supersedes the `GoalRunner`-based wording below. Goals execute through
`DurableGoalCoordinator` (`core/goals/coordinator.py`) and a `DurableWorker`
(`services/worker_service.py`); `agents/andromeda/goal_runner.py` is not
reachable from `services/`. Consequences:

- Failover, budget check, pause and auto-resume live in
  `DurableGoalCoordinator.reconcile` / `reconcile_all` (driven by the worker's
  `cycle_hook`), not in a runner. "Heartbeat" = that worker cycle.
- Metering and the model override are set by a goal-aware executor wrapped
  around `Andromeda.route` in the worker, keyed off `TaskContract.origin`
  (`goal:<id>`). The result carries `model_tier` so concurrent in-flight
  tasks are classified correctly.
- `Andromeda._execute_node` swallows all exceptions and `failed` escalates to
  the review queue, so `LLMQuotaError` gets its own terminal graph node
  returning `failed` / `provider_quota`.
- Re-dispatch after a quota failure uses idempotency key suffix `:q<n>`
  (n = recorded `provider_quota` events for that task).
- Planning tokens (`GoalPlanner`, run in the API process) are not metered.
- Implementation plan: `docs/plans/2026-10-12-goal-token-budget.md`.

## Problem

Nothing bounds how much a goal can spend, and a provider running out of quota
mid-goal fails tasks with no recovery path.

- `GoalRunner` executes a planned DAG to completion; every task may make several
  LLM calls plus retries.
- Eight of the ten `call_llm()` sites discard returned token counts
  (`text, _, _ =`), so usage is not observable per goal.
  `GoalReport.estimated_cost` (`core/evaluation/reporting.py`) is never populated.
- Quota/rate-limit errors from the provider surface as a generic
  `RuntimeError("LLM call failed: ...")` and fail the task.

Two distinct mechanisms, deliberately separate:

| Trigger | Response |
|---|---|
| Goal's own **token cap** reached | Pause the goal. No failover (a second model does not reset the cap). Manual resume with a new budget. |
| **Provider quota / rate-limit** error | Fail over to the platform fallback model once; if that also fails, pause and auto-resume on the primary after 15 minutes. |

Out of scope: dollar cost, per-agent / per-org budgets, warning thresholds,
mid-call abort.

## Design

### Contract (updated first, per project rule)

`GoalContract` in `core/contracts/contracts.py` gains platform-written fields
unless noted:

```python
"token_budget": int | None        # caller-supplied; None = unlimited (today's behaviour)
"tokens_used": int                # prompt + output; default 0
"fallback_used": bool             # True once failover happened in the current attempt
"resume_after": datetime | None   # set when paused for provider quota
"pause_reason": str | None        # "token_budget" | "provider_quota"
```

`POST /goals` accepts optional `token_budget`. `GET /goals/{id}` returns the
fields above. `POST /goals/{id}/resume` accepts an optional new `token_budget`
(resuming a token-paused goal with the same budget re-pauses immediately).
`GoalStore` and `postgres_store` add the columns with default-safe migrations
(existing rows: `token_budget NULL`, `tokens_used 0`, `fallback_used false`).

There is no per-goal fallback model field: the fallback is platform-wide.

### Config

`config/providers.yaml` gains an optional `llm.fallback` block (same shape as
the primary provider entry). Absent → failover is disabled and a provider quota
error pauses the goal immediately. Retry delay is
`LLM_QUOTA_RESUME_DELAY_SECONDS`, default `900` (15 min).

### Metering

- `core/llm/provider.py`: a `ContextVar` holding the active goal meter.
  `call_llm()` adds `prompt_tokens + output_tokens` after each response.
  Signature and return value unchanged → no call-site changes.
- `GoalRunner` sets the context var around each `Andromeda.route()` call and
  persists the delta with an atomic
  `UPDATE goals SET tokens_used = tokens_used + ?`.
- Planning (`GoalPlanner`) calls count against the same goal. Tokens spent on
  the fallback model count toward the same cap.

### Provider failover

- New `LLMQuotaError(RuntimeError)` in `core/llm/provider.py`, raised by
  `call_llm()` when litellm raises `RateLimitError` or `BudgetExceededError`
  (including HTTP 429 / insufficient-quota). It subclasses `RuntimeError`, so
  the existing `RuntimeError` convention and every caller are unaffected.
- A second `ContextVar` carries a model override. When set, `call_llm()` swaps
  in the fallback provider/model/base_url/key for that goal's calls.
- `GoalRunner`, on `LLMQuotaError` from a task:
  1. `fallback_used = false` and a fallback is configured → set
     `fallback_used = true`, set the override, re-dispatch the same task once.
     This does not consume the task's normal retry count.
  2. Otherwise (fallback already used and failed, or none configured) → goal
     `paused`, `pause_reason = "provider_quota"`,
     `resume_after = now + delay`.
- Only quota-class errors trigger failover. A fallback model returning bad
  output follows the existing retry/escalate path unchanged.

### Enforcement and resume

- Token cap is checked before dispatching each task, not mid-call. At
  `tokens_used >= token_budget` the goal pauses with
  `pause_reason = "token_budget"` and `resume_after = None`. In-flight work
  finishes, so overshoot is bounded by one task.
- Auto-resume: a periodic check finds goals with `status = 'paused'`,
  `pause_reason = 'provider_quota'` and `resume_after <= now`, clears
  `fallback_used` and the override, and re-claims via the existing
  `try_claim`, so the goal restarts on the **primary** model. The hook point
  (the `core/jobs` worker tick vs. a loop in `andromeda_service.py`) is to be
  confirmed during planning; the choice must not add a second scheduler.
- Failover is once per attempt: if the primary fails again after the 15 min
  resume, the fallback gets one more try, then the goal pauses again.

## Known limits

- Metering and the model override are in-process. With
  `--profile distributed-agents`, Vega and Rigel run in separate processes:
  their tokens are not metered and the override does not reach them. Closing
  this needs usage and a quota-error marker carried in the task result
  (a contract change) — follow-up.
- Tokens, not money: a cap of N tokens costs different amounts per model.
- `RateLimitError` can also be transient throttling rather than exhausted
  quota; it is treated as quota here and fixed delay absorbs it.

## Testing

`test/core/test_goal_budget.py` and `test/core/test_goal_failover.py`, LLM mocked:

- tokens accumulate across tasks; `token_budget=None` never pauses; goal pauses
  before the task after exhaustion and not before; in-flight task completes;
  resume with larger budget continues, with same budget re-pauses.
- quota error on primary → same task re-dispatched on fallback, retry count
  untouched; fallback quota error → goal paused with `resume_after` ≈ now+15 min;
  non-quota failure on fallback does not pause; no fallback configured → pauses
  immediately; token-cap pause is never auto-resumed.
- resume tick: not-yet-due goal untouched; due goal restarts on primary with
  `fallback_used` cleared; failover available again after resume.
- two concurrent goals do not leak meter or override into each other;
  migration leaves existing rows valid. Full existing suite stays green.

## Out of scope

Dollar cost, per-goal fallback model, multiple fallbacks, per-agent / per-org /
global budgets, warning thresholds, mid-call abort, cross-process metering.
