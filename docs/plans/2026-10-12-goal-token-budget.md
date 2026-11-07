# Goal Token Budget and Provider Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap tokens per goal (pause when spent) and, on provider quota/rate-limit errors, fail over once to a platform fallback model, then pause and auto-resume on the primary after a fixed delay.

**Architecture:** Metering and the model override are `contextvars` set by a goal-aware executor wrapped around `andromeda.route` in the durable worker. Failover, pausing, budget enforcement and auto-resume live in `DurableGoalCoordinator.reconcile` so they are restart-safe and driven by the worker's existing `cycle_hook`. Andromeda gets one new terminal node so a quota error is a clean `failed/provider_quota` result instead of a junk review-queue escalation.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite (`GoalStore`) + SQLAlchemy/Alembic (`PostgresGoalStore`), LangGraph, litellm, pytest.

**Spec:** `docs/specs/2026-10-12-goal-token-budget-design.md` (see its "Revision" block: the mechanism below supersedes the `GoalRunner`-based wording).

## Global Constraints

- Contracts first: `GoalContract` changes land (Task 1) before any implementation that reads them.
- `call_llm()` signature and `tuple[str, int, int]` return are unchanged; no call-site edits. `LLMQuotaError` subclasses `RuntimeError`.
- Failover is once per attempt (per goal, until the goal is resumed). Fallback model is platform-wide from `llm.fallback` in `config/providers.yaml`; absent/blank/unresolved `${VAR}` means disabled. There is no per-goal fallback field.
- Provider-quota auto-resume delay: `LLM_QUOTA_RESUME_DELAY_SECONDS`, default `900`.
- Token-cap pause is never auto-resumed. Budget is checked before dispatch, not mid-call.
- Only quota-class errors (`litellm.RateLimitError`, `litellm.BudgetExceededError`) trigger failover; every other failure follows the existing retry/escalate path unchanged.
- Legacy `agents/andromeda/goal_runner.py` is not reachable from `services/` and is left untouched.
- One logical change per commit. No `Co-Authored-By: Claude` trailer on commits (project memory rule).
- Keep the existing suite green: `pytest -q` must pass after every task.

## Review Focus

1. Two tasks in flight both hit quota on the primary → exactly one `failover` event, neither pauses, both re-dispatched on the fallback (Task 6).
2. Crash/restart after a task was reset to `pending` for failover → a fresh coordinator dispatches it exactly once under the `:q<n>` key, not a duplicate (Task 6).
3. A goal paused for human review (`pause_reason` NULL) or for token cap is never touched by the auto-resume tick (Task 6).
4. Fallback block present but env var unset (`${X}` literal) or blank → treated as disabled, not as a model named `${X}` (Task 3).
5. Last task finishes while `tokens_used >= token_budget` → goal completes, it is not paused (Task 6).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `core/contracts/contracts.py` | modify | `GoalContract` budget/failover fields |
| `core/goals/store.py` | modify | SQLite columns, migration, budget/pause methods, `goal_tree` fields |
| `core/llm/provider.py` | modify | `LLMQuotaError`, `UsageMeter`, `metered_call`, fallback config loader |
| `agents/andromeda/orchestrator.py` | modify | quota error → `failed/provider_quota`, new terminal node |
| `core/goals/executor.py` | create | `make_goal_executor`: meter + override around `route` |
| `services/worker_service.py` | modify | use the goal executor |
| `core/goals/coordinator.py` | modify | failover, pause, budget check, auto-resume |
| `services/andromeda_service.py` | modify | `token_budget` on `POST /goals`, body on `/resume` |
| `core/storage/migrations/versions/v0004_goal_budget.py` | create | Postgres columns |
| `core/goals/postgres_store.py` | modify | Postgres parity |
| `test/goals/test_contracts_goals.py` | modify | contract tests |
| `test/goals/test_goal_budget_store.py` | create | store tests |
| `test/core/test_llm_quota.py` | create | provider tests |
| `test/agents/test_andromeda_provider_quota.py` | create | routing tests |
| `test/goals/test_goal_executor.py` | create | executor tests |
| `test/goals/test_goal_budget_coordinator.py` | create | coordinator tests |
| `test/api/test_goals_budget_api.py` | create | API tests |
| `test/goals/test_postgres_goal_budget.py` | create | Postgres store tests |

---

### Task 1: GoalContract fields

**Files:**
- Modify: `core/contracts/contracts.py:156-174`
- Test: `test/goals/test_contracts_goals.py`

**Interfaces:**
- Produces: `GoalContract.token_budget: int | None` (≥1), `tokens_used: int` (≥0, default 0), `fallback_used: bool` (default False), `resume_after: datetime | None`, `pause_reason: Literal["token_budget","provider_quota"] | None`.

- [ ] **Step 1: Write the failing tests** — append to `test/goals/test_contracts_goals.py`:

```python
def test_goal_budget_defaults():
    g = GoalContract(origin="t", objective="x", confidence_threshold=0.65)
    assert g.token_budget is None
    assert g.tokens_used == 0
    assert g.fallback_used is False
    assert g.resume_after is None
    assert g.pause_reason is None


def test_goal_token_budget_must_be_positive():
    with pytest.raises(ValidationError):
        GoalContract(origin="t", objective="x", confidence_threshold=0.65, token_budget=0)


def test_goal_pause_reason_is_constrained():
    with pytest.raises(ValidationError):
        GoalContract(origin="t", objective="x", confidence_threshold=0.65, pause_reason="bogus")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/goals/test_contracts_goals.py -q`
Expected: 3 FAIL (`AttributeError`/`ValidationError` not raised).

- [ ] **Step 3: Implement** — in `core/contracts/contracts.py`, after the `GoalStatus` literal add:

```python
PauseReason = Literal["token_budget", "provider_quota"]
```

and inside `GoalContract`, after `plan_confidence`:

```python
    token_budget: int | None = Field(default=None, ge=1)  # None = unlimited
    tokens_used: int = Field(default=0, ge=0)  # platform-written
    fallback_used: bool = False  # platform-written: failover happened this attempt
    resume_after: datetime | None = None  # platform-written: provider_quota auto-resume time
    pause_reason: PauseReason | None = None  # platform-written
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/goals/test_contracts_goals.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/contracts/contracts.py test/goals/test_contracts_goals.py
git commit -m "feat(goals): add token budget and failover fields to GoalContract"
```

---

### Task 2: GoalStore persistence and methods

**Files:**
- Modify: `core/goals/store.py` (`__init__` column migration near line 94, `create_goal` line 110, `get_goal` line 123, new methods after `set_goal_status` line 155, `goal_tree` line 346)
- Test: `test/goals/test_goal_budget_store.py` (create)

**Interfaces:**
- Consumes: Task 1 fields.
- Produces on `GoalStore`: `add_tokens_used(goal_id: UUID, tokens: int) -> None`, `set_fallback_used(goal_id: UUID, used: bool) -> None`, `set_token_budget(goal_id: UUID, token_budget: int | None) -> None`, `pause_with_reason(goal_id: UUID, reason: str, resume_after: datetime | None) -> None` (sets status `paused`), `clear_pause(goal_id: UUID) -> None` (clears `pause_reason`, `resume_after`, `fallback_used`; leaves status). `goal_tree()["goal"]` gains `token_budget`, `tokens_used`, `fallback_used`, `pause_reason`, `resume_after`.

- [ ] **Step 1: Write the failing tests** — create `test/goals/test_goal_budget_store.py`:

```python
import sqlite3
from datetime import datetime, timezone

from core.contracts import GoalContract
from core.goals import GoalStore


def _goal(**kw) -> GoalContract:
    return GoalContract(origin="t", objective="x", confidence_threshold=0.65, **kw)


def test_budget_fields_round_trip(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=500)
    store.create_goal(goal)
    got = store.get_goal(goal.goal_id)
    assert got.token_budget == 500
    assert got.tokens_used == 0
    assert got.fallback_used is False
    assert got.pause_reason is None and got.resume_after is None


def test_add_tokens_used_accumulates(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal()
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 30)
    store.add_tokens_used(goal.goal_id, 12)
    assert store.get_goal(goal.goal_id).tokens_used == 42


def test_pause_with_reason_then_clear(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal()
    store.create_goal(goal)
    when = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    store.pause_with_reason(goal.goal_id, "provider_quota", when)
    store.set_fallback_used(goal.goal_id, True)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused"
    assert got.pause_reason == "provider_quota"
    assert got.resume_after == when
    assert got.fallback_used is True

    store.clear_pause(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused"  # clear_pause does not change status
    assert got.pause_reason is None and got.resume_after is None
    assert got.fallback_used is False


def test_set_token_budget(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=10)
    store.create_goal(goal)
    store.set_token_budget(goal.goal_id, 99)
    assert store.get_goal(goal.goal_id).token_budget == 99
    store.set_token_budget(goal.goal_id, None)
    assert store.get_goal(goal.goal_id).token_budget is None


def test_existing_database_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE goals (goal_id TEXT PRIMARY KEY, origin TEXT NOT NULL, "
        "objective TEXT NOT NULL, confidence_threshold REAL NOT NULL, "
        "status TEXT NOT NULL, plan_confidence REAL, created_at TEXT NOT NULL)"
    )
    gid = "11111111-1111-1111-1111-111111111111"
    conn.execute(
        "INSERT INTO goals VALUES (?, 'o', 'obj', 0.65, 'running', NULL, "
        "'2026-01-01T00:00:00+00:00')",
        (gid,),
    )
    conn.commit()
    conn.close()

    from uuid import UUID
    got = GoalStore(path).get_goal(UUID(gid))
    assert got.token_budget is None
    assert got.tokens_used == 0
    assert got.fallback_used is False


def test_goal_tree_exposes_budget_fields(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=250)
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 7)
    tree = store.goal_tree(goal.goal_id)["goal"]
    assert tree["token_budget"] == 250
    assert tree["tokens_used"] == 7
    assert tree["fallback_used"] is False
    assert tree["pause_reason"] is None
    assert tree["resume_after"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/goals/test_goal_budget_store.py -q`
Expected: FAIL (`AttributeError: add_tokens_used`, `sqlite3.OperationalError`).

- [ ] **Step 3: Implement** — in `core/goals/store.py`:

(a) in `__init__`, immediately after the `workspace_root` migration block and before `self._conn.commit()`:

```python
        for name, ddl in (
            ("token_budget", "INTEGER"),
            ("tokens_used", "INTEGER NOT NULL DEFAULT 0"),
            ("fallback_used", "INTEGER NOT NULL DEFAULT 0"),
            ("resume_after", "TEXT"),
            ("pause_reason", "TEXT"),
        ):
            if name not in goal_columns:
                self._conn.execute(f"ALTER TABLE goals ADD COLUMN {name} {ddl}")
```

(b) `create_goal`: add `token_budget` to the column list and values (the other new columns take their defaults):

```python
                "INSERT INTO goals (goal_id, origin, objective, confidence_threshold, "
                "status, plan_confidence, created_at, workspace_root, token_budget) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(goal.goal_id), goal.origin, goal.objective,
                    goal.confidence_threshold, goal.status, goal.plan_confidence,
                    goal.created_at.isoformat(), goal.workspace_root, goal.token_budget,
                ),
```

(c) `get_goal`: extend the `GoalContract(...)` call:

```python
            token_budget=row["token_budget"],
            tokens_used=row["tokens_used"],
            fallback_used=bool(row["fallback_used"]),
            resume_after=row["resume_after"],
            pause_reason=row["pause_reason"],
```

(d) new methods after `set_goal_status`:

```python
    def add_tokens_used(self, goal_id: UUID, tokens: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET tokens_used = tokens_used + ? WHERE goal_id = ?",
                (tokens, str(goal_id)),
            )
            self._conn.commit()

    def set_fallback_used(self, goal_id: UUID, used: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET fallback_used = ? WHERE goal_id = ?",
                (1 if used else 0, str(goal_id)),
            )
            self._conn.commit()

    def set_token_budget(self, goal_id: UUID, token_budget: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET token_budget = ? WHERE goal_id = ?",
                (token_budget, str(goal_id)),
            )
            self._conn.commit()

    def pause_with_reason(
        self, goal_id: UUID, reason: str, resume_after: datetime | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status = 'paused', pause_reason = ?, resume_after = ? "
                "WHERE goal_id = ?",
                (reason, resume_after.isoformat() if resume_after else None, str(goal_id)),
            )
            self._conn.commit()

    def clear_pause(self, goal_id: UUID) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET pause_reason = NULL, resume_after = NULL, "
                "fallback_used = 0 WHERE goal_id = ?",
                (str(goal_id),),
            )
            self._conn.commit()
```

(e) `goal_tree`: after `"objective": goal.objective,` add:

```python
                "token_budget": goal.token_budget,
                "tokens_used": goal.tokens_used,
                "fallback_used": goal.fallback_used,
                "pause_reason": goal.pause_reason,
                "resume_after": goal.resume_after.isoformat() if goal.resume_after else None,
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/goals -q`
Expected: all PASS (existing goal tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add core/goals/store.py test/goals/test_goal_budget_store.py
git commit -m "feat(goals): persist token budget, usage and pause metadata"
```

---

### Task 3: Provider metering, quota error, fallback config

**Files:**
- Modify: `core/llm/provider.py` (imports line 1-12, `call_llm` from line 83, new loader after `load_provider_config`)
- Test: `test/core/test_llm_quota.py` (create)

**Interfaces:**
- Produces: `LLMQuotaError(RuntimeError)`; `UsageMeter` with `.tokens: int`; `metered_call(meter: UsageMeter, override: ProviderConfig | None = None)` context manager; `load_fallback_provider_config(config_path: str = "config/providers.yaml") -> ProviderConfig | None`.

- [ ] **Step 1: Write the failing tests** — create `test/core/test_llm_quota.py`:

```python
from types import SimpleNamespace

import litellm
import pytest

from core.llm import provider
from core.llm.provider import (
    LLMQuotaError,
    ProviderConfig,
    UsageMeter,
    call_llm,
    load_fallback_provider_config,
    metered_call,
)

PRIMARY = ProviderConfig(provider="openai", model="primary")
BACKUP = ProviderConfig(provider="openai", model="backup")
MSG = [{"role": "user", "content": "hi"}]


def _response(prompt=7, completion=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


class _RateLimited(litellm.RateLimitError):
    def __init__(self):
        Exception.__init__(self, "429 slow down")


def test_meter_accumulates_tokens(monkeypatch):
    monkeypatch.setattr(provider.litellm, "completion", lambda **kw: _response())
    meter = UsageMeter()
    with metered_call(meter):
        call_llm(MSG, PRIMARY)
        call_llm(MSG, PRIMARY)
    assert meter.tokens == 20


def test_calls_outside_a_meter_context_still_work(monkeypatch):
    monkeypatch.setattr(provider.litellm, "completion", lambda **kw: _response())
    assert call_llm(MSG, PRIMARY) == ("ok", 7, 3)


def test_override_swaps_the_model(monkeypatch):
    seen = []
    monkeypatch.setattr(
        provider.litellm, "completion", lambda **kw: seen.append(kw["model"]) or _response()
    )
    with metered_call(UsageMeter(), override=BACKUP):
        call_llm(MSG, PRIMARY)
    call_llm(MSG, PRIMARY)
    assert seen == ["openai/backup", "openai/primary"]


def test_rate_limit_becomes_quota_error(monkeypatch):
    def boom(**kw):
        raise _RateLimited()

    monkeypatch.setattr(provider.litellm, "completion", boom)
    with pytest.raises(LLMQuotaError) as exc:
        call_llm(MSG, PRIMARY)
    assert isinstance(exc.value, RuntimeError)


def test_other_errors_stay_plain_runtime_errors(monkeypatch):
    def boom(**kw):
        raise ValueError("bad request")

    monkeypatch.setattr(provider.litellm, "completion", boom)
    with pytest.raises(RuntimeError) as exc:
        call_llm(MSG, PRIMARY)
    assert not isinstance(exc.value, LLMQuotaError)


def _yaml(tmp_path, body: str) -> str:
    path = tmp_path / "providers.yaml"
    path.write_text(body)
    return str(path)


def test_fallback_loaded_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("FB_MODEL", "claude-x")
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_MODEL}\n")
    cfg = load_fallback_provider_config(path)
    assert (cfg.provider, cfg.model) == ("anthropic", "claude-x")


def test_fallback_absent_is_none(tmp_path):
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n")
    assert load_fallback_provider_config(path) is None


def test_fallback_with_unset_env_var_is_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FB_NOPE", raising=False)
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_NOPE}\n")
    assert load_fallback_provider_config(path) is None


def test_fallback_with_blank_default_is_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FB_BLANK", raising=False)
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_BLANK:-}\n")
    assert load_fallback_provider_config(path) is None


def test_missing_config_file_is_none(tmp_path):
    assert load_fallback_provider_config(str(tmp_path / "nope.yaml")) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/core/test_llm_quota.py -q`
Expected: collection ERROR (`ImportError: cannot import name 'LLMQuotaError'`).

- [ ] **Step 3: Implement** — in `core/llm/provider.py`:

(a) imports: add `import contextvars` and `from contextlib import contextmanager`.

(b) after `_limiter = ProviderLimiter()` add:

```python
_QUOTA_ERRORS = tuple(
    err
    for err in (
        getattr(litellm, "RateLimitError", None),
        getattr(litellm, "BudgetExceededError", None),
    )
    if err is not None
)


class LLMQuotaError(RuntimeError):
    """The provider rejected the call because quota or rate limit is exhausted."""


class UsageMeter:
    def __init__(self) -> None:
        self.tokens = 0


_meter: contextvars.ContextVar["UsageMeter | None"] = contextvars.ContextVar(
    "llm_usage_meter", default=None
)
_override: contextvars.ContextVar["ProviderConfig | None"] = contextvars.ContextVar(
    "llm_provider_override", default=None
)
```

(c) after the `ProviderConfig` dataclass add the context manager (it references `ProviderConfig`, so it must follow it):

```python
@contextmanager
def metered_call(meter: UsageMeter, override: "ProviderConfig | None" = None):
    meter_token = _meter.set(meter)
    override_token = _override.set(override)
    try:
        yield meter
    finally:
        _meter.reset(meter_token)
        _override.reset(override_token)
```

(d) after `load_provider_config` add:

```python
def load_fallback_provider_config(
    config_path: str = "config/providers.yaml",
) -> Optional[ProviderConfig]:
    """Platform fallback model from ``llm.fallback``; None when absent or unresolved."""
    if not os.path.exists(config_path):
        return None
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    block = (raw.get("llm") or {}).get("fallback")
    if not block:
        return None
    provider = _resolve_env_vars(str(block.get("provider") or "")).strip()
    model = _resolve_env_vars(str(block.get("model") or "")).strip()
    if not provider or not model or "${" in provider or "${" in model:
        return None
    api_key = _resolve_env_vars(str(block["api_key"])) if block.get("api_key") else None
    base_url = _resolve_env_vars(str(block["base_url"])) if block.get("base_url") else None
    return ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key or None,
        base_url=base_url or None,
    )
```

(e) in `call_llm`, directly after `messages = list(messages)` add:

```python
    override = _override.get()
    if override is not None:
        config = override
```

(f) in the `except` chain, insert before `except Exception as e:`:

```python
    except _QUOTA_ERRORS as e:
        raise LLMQuotaError(f"LLM quota exhausted: {e}") from e
```

(g) before `return text, prompt_tokens, output_tokens` add:

```python
    meter = _meter.get()
    if meter is not None:
        meter.tokens += prompt_tokens + output_tokens
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/core/test_llm_quota.py test/core/test_llm_limiter.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/llm/provider.py test/core/test_llm_quota.py
git commit -m "feat(llm): usage metering, quota error and fallback provider config"
```

---

### Task 4: Andromeda — quota error is a clean failure

**Files:**
- Modify: `agents/andromeda/orchestrator.py` (imports; `_make_after_execute` line 116; node registration line 272-276; edges line 297-301; `_execute_node` except clause line 387; new module-level node after `_complete_node`)
- Test: `test/agents/test_andromeda_provider_quota.py` (create)

**Interfaces:**
- Consumes: `LLMQuotaError` (Task 3).
- Produces: `route()` returns `status == "failed"`, `failure_reason == "provider_quota"`, no review-queue item, no retry.

- [ ] **Step 1: Write the failing tests** — create `test/agents/test_andromeda_provider_quota.py`:

```python
import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.llm.provider import LLMQuotaError
from core.pulsar.registry import PulsarRegistry


class RaisingAgent:
    def __init__(self, exc: Exception):
        self.exc = exc

    def run(self, skill_id, payload, context):
        raise self.exc


@pytest.fixture
def registry(tmp_path):
    reg = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    reg.register(
        SkillManifest(
            agent_id="fake", agent_name="Fake", version="1.0.0",
            skills=[SkillDefinition(
                skill_id="fake.skill.echo", description="echo",
                input_schema={}, output_schema={},
            )],
            health_endpoint="/health",
        )
    )
    return reg


def _route(registry, tmp_path, exc):
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"fake": RaisingAgent(exc)},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
    )
    task = TaskContract(origin="test", skill="fake.skill.echo", payload={}, confidence_threshold=0.65)
    return andromeda, andromeda.route(task=task)


def test_quota_error_fails_cleanly_without_a_review_item(registry, tmp_path):
    andromeda, result = _route(registry, tmp_path, LLMQuotaError("429"))
    assert result["status"] == "failed"
    assert result["failure_reason"] == "provider_quota"
    assert andromeda.review_queue.get_by_task_id(result["task_id"]) is None


def test_other_errors_still_escalate(registry, tmp_path):
    _, result = _route(registry, tmp_path, RuntimeError("boom"))
    assert result["status"] == "escalated"
    assert result["failure_reason"] == "boom"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/agents/test_andromeda_provider_quota.py -q`
Expected: `test_quota_error_fails_cleanly_without_a_review_item` FAIL (`status == "escalated"`); the regression test PASSES.

- [ ] **Step 3: Implement** — in `agents/andromeda/orchestrator.py`:

(a) add import near the other `core` imports: `from core.llm.provider import LLMQuotaError`.

(b) in `_after_execute` (inside `_make_after_execute`), as the first statement:

```python
        if state.get("failure_reason") == "provider_quota":
            return "quota_exhausted"
```

(c) after `_complete_node` add:

```python
def _quota_exhausted_node(state: AndromedaState) -> dict:
    return {
        "status": "failed",
        "failure_reason": "provider_quota",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
```

(d) register in the graph: next to `g.add_node("no_agent_found", ...)` add `g.add_node("quota_exhausted", _quota_exhausted_node)`; in the `execute` conditional-edge map add `"quota_exhausted": "quota_exhausted",`; next to `g.add_edge("no_agent_found", END)` add `g.add_edge("quota_exhausted", END)`.

(e) in `_execute_node`, before `except Exception as e:` add:

```python
        except LLMQuotaError:
            return {
                "status": "failed",
                "failure_reason": "provider_quota",
                "confidence": 0.0,
            }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/agents -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/andromeda/orchestrator.py test/agents/test_andromeda_provider_quota.py
git commit -m "feat(andromeda): treat provider quota errors as a clean failed result"
```

---

### Task 5: Goal-aware executor and worker wiring

**Files:**
- Create: `core/goals/executor.py`
- Modify: `services/worker_service.py` (imports; `execute` definition lines 45-49)
- Test: `test/goals/test_goal_executor.py` (create)

**Interfaces:**
- Consumes: `UsageMeter`, `metered_call`, `ProviderConfig` (Task 3); `GoalStore.add_tokens_used`, `get_goal` (Task 2).
- Produces: `make_goal_executor(route, store, fallback: ProviderConfig | None) -> Callable[[TaskContract, CancellationToken], dict]`. For goal-origin tasks the returned dict gains `"model_tier": "primary" | "fallback"`.

- [ ] **Step 1: Write the failing tests** — create `test/goals/test_goal_executor.py`:

```python
from types import SimpleNamespace

import pytest

from core.contracts import GoalContract, TaskContract
from core.goals import GoalStore
from core.goals.executor import make_goal_executor
from core.llm import provider
from core.llm.provider import ProviderConfig, call_llm

PRIMARY = ProviderConfig(provider="openai", model="primary")
BACKUP = ProviderConfig(provider="openai", model="backup")


class _Token:
    def raise_if_cancelled(self):
        pass


def _llm(monkeypatch, seen):
    def completion(**kw):
        seen.append(kw["model"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=6, completion_tokens=4),
        )

    monkeypatch.setattr(provider.litellm, "completion", completion)


def _route(task):
    call_llm([{"role": "user", "content": "hi"}], PRIMARY)
    return {"status": "complete", "confidence": 0.9}


def _setup(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.65)
    store.create_goal(goal)
    task = TaskContract(
        origin=f"goal:{goal.goal_id}", skill="s", payload={}, confidence_threshold=0.65
    )
    return store, goal, task


def test_non_goal_origin_passes_through(tmp_path, monkeypatch):
    _llm(monkeypatch, [])
    store, _, _ = _setup(tmp_path)
    task = TaskContract(origin="api", skill="s", payload={}, confidence_threshold=0.65)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result == {"status": "complete", "confidence": 0.9}


def test_tokens_persisted_and_tier_primary(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result["model_tier"] == "primary"
    assert seen == ["openai/primary"]
    assert store.get_goal(goal.goal_id).tokens_used == 10


def test_fallback_used_routes_to_fallback_model(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    store.set_fallback_used(goal.goal_id, True)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result["model_tier"] == "fallback"
    assert seen == ["openai/backup"]


def test_fallback_flag_without_configured_fallback_stays_primary(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    store.set_fallback_used(goal.goal_id, True)
    result = make_goal_executor(_route, store, None)(task, _Token())
    assert result["model_tier"] == "primary"
    assert seen == ["openai/primary"]


def test_tokens_persisted_even_when_route_raises(tmp_path, monkeypatch):
    _llm(monkeypatch, [])
    store, goal, task = _setup(tmp_path)

    def failing(task):
        call_llm([{"role": "user", "content": "hi"}], PRIMARY)
        raise RuntimeError("after the call")

    with pytest.raises(RuntimeError):
        make_goal_executor(failing, store, BACKUP)(task, _Token())
    assert store.get_goal(goal.goal_id).tokens_used == 10
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/goals/test_goal_executor.py -q`
Expected: collection ERROR (`No module named 'core.goals.executor'`).

- [ ] **Step 3: Implement** — create `core/goals/executor.py`:

```python
from __future__ import annotations

from typing import Callable
from uuid import UUID

from core.contracts import TaskContract
from core.llm.provider import ProviderConfig, UsageMeter, metered_call


def goal_id_from_origin(origin: str) -> UUID | None:
    if not origin.startswith("goal:"):
        return None
    try:
        return UUID(origin.removeprefix("goal:"))
    except ValueError:
        return None


def make_goal_executor(
    route: Callable[..., dict],
    store,
    fallback: ProviderConfig | None,
) -> Callable[[TaskContract, object], dict]:
    """Wrap ``Andromeda.route`` so goal tasks are metered and honour failover."""

    def execute(task: TaskContract, token) -> dict:
        token.raise_if_cancelled()
        goal_id = goal_id_from_origin(task.origin)
        if goal_id is None:
            result = route(task=task)
            token.raise_if_cancelled()
            return result

        goal = store.get_goal(goal_id)
        use_fallback = bool(goal is not None and goal.fallback_used and fallback is not None)
        meter = UsageMeter()
        try:
            with metered_call(meter, fallback if use_fallback else None):
                result = route(task=task)
        finally:
            if meter.tokens:
                store.add_tokens_used(goal_id, meter.tokens)
        token.raise_if_cancelled()
        return {**result, "model_tier": "fallback" if use_fallback else "primary"}

    return execute
```

In `services/worker_service.py`: replace the `execute` function (lines 45-49) with

```python
    config_path = os.getenv("GALAXZ_CONFIG_PATH", "config/providers.yaml")
    execute = make_goal_executor(
        andromeda.route, andromeda.goal_store, load_fallback_provider_config(config_path)
    )
```

and use `config_path` in the `boot(...)` call two lines up (`andromeda = boot(config_path)` — move the `config_path =` line above `boot`). Imports: remove the now-unused `TaskContract` and `CancellationToken` imports; add
`from core.goals.executor import make_goal_executor` and `from core.llm.provider import load_fallback_provider_config`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/goals/test_goal_executor.py -q && python -c "import services.worker_service"`
Expected: PASS, import succeeds.

- [ ] **Step 5: Commit**

```bash
git add core/goals/executor.py services/worker_service.py test/goals/test_goal_executor.py
git commit -m "feat(goals): meter goal tasks and route to fallback model in the worker"
```

---

### Task 6: Coordinator — failover, budget pause, auto-resume

**Files:**
- Modify: `core/goals/coordinator.py`
- Test: `test/goals/test_goal_budget_coordinator.py` (create)

**Interfaces:**
- Consumes: store methods (Task 2); result keys `failure_reason == "provider_quota"` and `model_tier` (Tasks 4–5); `load_fallback_provider_config` (Task 3).
- Produces: `DurableGoalCoordinator(..., quota_resume_delay_s: float | None = None, fallback_enabled: bool | None = None)`. Events recorded: `provider_quota` (affected task), `failover`, `pause` (reason `provider_quota`|`token_budget`). Re-dispatch idempotency key `goal:<g>:task:<t>:q<n>`.

- [ ] **Step 1: Write the failing tests** — create `test/goals/test_goal_budget_coordinator.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.contracts import GoalContract, PlannedTask, ProjectNode
from core.goals import DurableGoalCoordinator, GoalStore
from core.jobs import SqliteJobRepository

QUOTA = {"status": "failed", "failure_reason": "provider_quota", "confidence": 0.0}


def _setup(tmp_path, *, token_budget=None, fallback_enabled=True, tasks=2, delay=900):
    store = GoalStore(str(tmp_path / "goals.db"))
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    goal = GoalContract(
        origin="t", objective="x", confidence_threshold=0.65, token_budget=token_budget
    )
    project = ProjectNode(goal_id=goal.goal_id, title="p")
    store.create_goal(goal)
    planned = []
    for i in range(tasks):
        planned.append(PlannedTask(
            project_id=project.project_id, goal_id=goal.goal_id,
            skill="rigel.skill.code_generation", payload={"i": i},
            depends_on=[planned[-1].task_id] if planned else [],
        ))
    store.save_plan(goal.goal_id, [project], planned, 0.9, gated=False)
    co = DurableGoalCoordinator(
        store, jobs, fallback_enabled=fallback_enabled, quota_resume_delay_s=delay
    )
    return store, jobs, co, goal, planned


def _finish(jobs, job_key, result):
    job = jobs.get_job_by_idempotency_key(job_key)
    claimed = jobs.claim(worker_id="w", lease_seconds=30)
    assert claimed is not None and claimed[0].job_id == job.job_id
    jobs.complete(
        job_id=job.job_id, lease_token=claimed[1].lease_token,
        output_ref=f"o:{job.job_id}", result=result,
    )


def _ok(**extra):
    return {"status": "complete", "confidence": 0.9, "result": {}, **extra}


def test_budget_exhausted_pauses_before_next_dispatch(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=100)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 120)
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "token_budget"
    assert got.resume_after is None
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is None


def test_no_budget_never_pauses(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=None)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 10**9)
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "running"
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is not None


def test_goal_completes_when_last_task_ends_over_budget(tmp_path):
    store, jobs, co, goal, (a,) = _setup(tmp_path, token_budget=10, tasks=1)
    co.start(goal.goal_id)
    store.add_tokens_used(goal.goal_id, 50)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "complete"


def test_budget_pause_not_auto_resumed_and_resume_with_same_budget_repauses(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=100)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 120)
    co.reconcile(goal.goal_id)
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"
    co.start(goal.goal_id)  # manual resume, budget unchanged
    assert store.get_goal(goal.goal_id).status == "paused"
    store.set_token_budget(goal.goal_id, 1000)
    co.start(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "running"
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is not None


def test_quota_on_primary_fails_over_once_and_redispatches(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is True
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, a.task_id)}:q1") is not None
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("failover") == 1


def test_two_in_flight_quota_failures_cause_one_failover_and_no_pause(tmp_path):
    store = GoalStore(str(tmp_path / "goals.db"))
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.65)
    project = ProjectNode(goal_id=goal.goal_id, title="p")
    store.create_goal(goal)
    a = PlannedTask(project_id=project.project_id, goal_id=goal.goal_id,
                    skill="rigel.skill.code_generation", payload={"i": 0})
    b = PlannedTask(project_id=project.project_id, goal_id=goal.goal_id,
                    skill="rigel.skill.code_generation", payload={"i": 1})
    store.save_plan(goal.goal_id, [project], [a, b], 0.9, gated=False)
    co = DurableGoalCoordinator(store, jobs, fallback_enabled=True, quota_resume_delay_s=900)
    co.start(goal.goal_id)
    for t in (a, b):
        _finish(jobs, co.key(goal.goal_id, t.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is True
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("failover") == 1
    for t in (a, b):
        assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, t.task_id)}:q1")


def test_quota_on_fallback_pauses_with_resume_after(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, delay=900)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    _finish(jobs, f"{co.key(goal.goal_id, a.task_id)}:q1", {**QUOTA, "model_tier": "fallback"})
    before = datetime.now(timezone.utc)
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    delta = (got.resume_after - before).total_seconds()
    assert 890 <= delta <= 910
    assert store.get_tasks(goal.goal_id)[0].status == "pending"


def test_no_fallback_configured_pauses_immediately(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, fallback_enabled=False)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert got.fallback_used is False


def test_due_quota_pause_auto_resumes_on_primary(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    _finish(jobs, f"{co.key(goal.goal_id, a.task_id)}:q1", {**QUOTA, "model_tier": "fallback"})
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "paused"

    store.pause_with_reason(
        goal.goal_id, "provider_quota", datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    co.reconcile_all()
    got = store.get_goal(goal.goal_id)
    assert got.status == "running"
    assert got.fallback_used is False and got.pause_reason is None
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, a.task_id)}:q2") is not None


def test_not_yet_due_and_review_pauses_are_left_alone(tmp_path):
    store, jobs, co, goal, _ = _setup(tmp_path)
    co.start(goal.goal_id)
    store.pause_with_reason(
        goal.goal_id, "provider_quota", datetime.now(timezone.utc) + timedelta(minutes=5)
    )
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"
    store.clear_pause(goal.goal_id)  # now a plain/review pause: pause_reason NULL
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"


def test_restart_after_failover_dispatches_exactly_once(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    restarted = DurableGoalCoordinator(
        GoalStore(str(tmp_path / "goals.db")),
        SqliteJobRepository(tmp_path / "jobs.db"),
        fallback_enabled=True,
    )
    restarted.reconcile_all()
    jobs_for_task = [
        j for j in jobs.list_jobs(limit=50)
        if (j.idempotency_key or "").startswith(co.key(goal.goal_id, a.task_id))
    ]
    assert len(jobs_for_task) == 2  # original + one :q1, no duplicate


def test_non_quota_failure_still_fails_the_goal(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id),
            {"status": "failed", "failure_reason": "boom", "confidence": 0.0})
    co.reconcile(goal.goal_id)
    assert store.get_tasks(goal.goal_id)[0].status == "failed"
    assert store.get_goal(goal.goal_id).status == "failed"


def test_start_clears_failover_state(tmp_path):
    store, jobs, co, goal, _ = _setup(tmp_path)
    store.set_goal_status(goal.goal_id, "ready")
    store.pause_with_reason(goal.goal_id, "provider_quota", None)
    store.set_fallback_used(goal.goal_id, True)
    co.start(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.fallback_used is False and got.pause_reason is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/goals/test_goal_budget_coordinator.py -q`
Expected: FAIL (`TypeError: unexpected keyword 'fallback_enabled'`).

- [ ] **Step 3: Implement** — in `core/goals/coordinator.py`:

(a) imports: add `from datetime import datetime, timedelta, timezone` and `from core.llm.provider import load_fallback_provider_config`.

(b) constructor: add parameters `quota_resume_delay_s: float | None = None, fallback_enabled: bool | None = None` and, at the end of `__init__`:

```python
        self.quota_resume_delay_s = (
            quota_resume_delay_s
            if quota_resume_delay_s is not None
            else float(os.getenv("LLM_QUOTA_RESUME_DELAY_SECONDS", "900"))
        )
        self.fallback_enabled = (
            fallback_enabled
            if fallback_enabled is not None
            else load_fallback_provider_config(
                os.getenv("GALAXZ_CONFIG_PATH", "config/providers.yaml")
            )
            is not None
        )
```

(c) helpers after `key`:

```python
    def _quota_counts(self, goal_id: UUID) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.store.events(goal_id):
            if event["action"] == "provider_quota":
                for task_id in event["affected"]:
                    counts[task_id] = counts.get(task_id, 0) + 1
        return counts

    def _dispatch_key(self, goal_id: UUID, task_id: UUID, counts: dict[str, int]) -> str:
        attempt = counts.get(str(task_id), 0)
        base = self.key(goal_id, task_id)
        return f"{base}:q{attempt}" if attempt else base

    def _handle_provider_quota(self, goal_id: UUID, task, tier: str) -> bool:
        """Reset the task for re-dispatch. Returns True when the goal was paused."""
        goal = self.store.get_goal(goal_id)
        self.store.record_event(
            goal_id, actor="system", action="provider_quota", reason=tier,
            affected=[str(task.task_id)],
        )
        self.store.update_task(task.task_id, status="pending", job_id=None, error=None)
        if tier == "primary" and (goal.fallback_used or self.fallback_enabled):
            if not goal.fallback_used:
                self.store.set_fallback_used(goal_id, True)
                self.store.record_event(
                    goal_id, actor="system", action="failover", reason="provider_quota"
                )
            return False
        resume_after = datetime.now(timezone.utc) + timedelta(seconds=self.quota_resume_delay_s)
        self.store.pause_with_reason(goal_id, "provider_quota", resume_after)
        self.store.record_event(
            goal_id, actor="system", action="pause", reason="provider_quota"
        )
        return True
```

(d) `reconcile_all`:

```python
    def reconcile_all(self) -> None:
        now = datetime.now(timezone.utc)
        for goal in self.store.list_active_goals():
            if (
                goal.status == "paused"
                and goal.pause_reason == "provider_quota"
                and goal.resume_after is not None
                and goal.resume_after <= now
            ):
                self.start(goal.goal_id, actor="system")
            elif goal.status != "paused":
                self.reconcile(goal.goal_id)
```

(e) `start`: after the status check, before `set_goal_status(... "running")`:

```python
        if goal.status == "paused":
            self.store.clear_pause(goal_id)
```

(f) `reconcile`: after `by_id = {...}` add `quota_counts = self._quota_counts(goal_id)`. Replace `self.key(goal_id, task.task_id)` in the `get_job_by_idempotency_key` lookup with `self._dispatch_key(goal_id, task.task_id, quota_counts)`. In the completed-job chain make the new branch first and turn the existing leading `if` into `elif`:

```python
                if state == "failed" and result.get("failure_reason") == "provider_quota":
                    if self._handle_provider_quota(
                        goal_id, task, result.get("model_tier", "primary")
                    ):
                        return
                elif state == "complete" and (confidence or 0.0) >= goal.confidence_threshold:
```

(g) immediately before `running = sum(task.status == "running" for task in tasks)` add:

```python
        quota_counts = self._quota_counts(goal_id)
        goal = self.store.get_goal(goal_id)
        if (
            goal.token_budget is not None
            and goal.tokens_used >= goal.token_budget
            and any(task.status == "pending" for task in tasks)
        ):
            self.store.pause_with_reason(goal_id, "token_budget", None)
            self.store.record_event(
                goal_id, actor="system", action="pause", reason="token_budget"
            )
            return
```

and change `idempotency_key=self.key(goal_id, task.task_id),` in the dispatch `enqueue` to `idempotency_key=self._dispatch_key(goal_id, task.task_id, quota_counts),`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/goals -q`
Expected: all PASS, including the untouched `test_durable_coordinator.py`.

- [ ] **Step 5: Commit**

```bash
git add core/goals/coordinator.py test/goals/test_goal_budget_coordinator.py
git commit -m "feat(goals): enforce token budget and provider failover in the coordinator"
```

---

### Task 7: API surface

**Files:**
- Modify: `services/andromeda_service.py` (`GoalRequest` line 247, `create_goal` line 994, `resume_goal` line 1156)
- Test: `test/api/test_goals_budget_api.py` (create)

**Interfaces:**
- Consumes: `GoalContract.token_budget`, `GoalStore.set_token_budget`.
- Produces: `POST /goals` accepts `token_budget` (≥1, else 422); `POST /goals/{id}/resume` accepts optional JSON `{"token_budget": int}`.

- [ ] **Step 1: Write the failing tests** — create `test/api/test_goals_budget_api.py` (reuses the fixture helpers from the existing API tests):

```python
from uuid import UUID

from test.api.test_goals_api import AUTH, client  # noqa: F401  (fixture re-export)


def test_post_goal_accepts_token_budget(client):
    r = client.post("/goals", json={"objective": "x", "token_budget": 5000}, headers=AUTH)
    assert r.status_code == 202
    goal = r.json()["goal"]
    assert goal["token_budget"] == 5000
    assert goal["tokens_used"] == 0


def test_post_goal_rejects_non_positive_budget(client):
    r = client.post("/goals", json={"objective": "x", "token_budget": 0}, headers=AUTH)
    assert r.status_code == 422


def test_resume_can_raise_the_budget(client):
    created = client.post(
        "/goals", json={"objective": "x", "token_budget": 10}, headers=AUTH
    ).json()["goal"]
    gid = created["goal_id"]
    client._andromeda.goal_store.pause_with_reason(UUID(gid), "token_budget", None)
    r = client.post(f"/goals/{gid}/resume", json={"token_budget": 9999}, headers=AUTH)
    assert r.status_code == 202
    assert r.json()["goal"]["token_budget"] == 9999


def test_resume_rejects_non_positive_budget(client):
    gid = client.post("/goals", json={"objective": "x"}, headers=AUTH).json()["goal"]["goal_id"]
    client._andromeda.goal_store.pause_with_reason(UUID(gid), "token_budget", None)
    r = client.post(f"/goals/{gid}/resume", json={"token_budget": 0}, headers=AUTH)
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/api/test_goals_budget_api.py -q`
Expected: FAIL (`KeyError: 'token_budget'` / status 202 instead of 422).

- [ ] **Step 3: Implement** — in `services/andromeda_service.py`:

(a) `GoalRequest`: add `token_budget: int | None = None`.

(b) add after `GoalRequest`:

```python
class GoalResumeRequest(BaseModel):
    token_budget: int | None = None
```

(c) in `create_goal`, before building the `GoalContract`:

```python
    if req.token_budget is not None and req.token_budget < 1:
        raise HTTPException(status_code=422, detail="token_budget must be >= 1")
```

and pass `token_budget=req.token_budget,` into the `GoalContract(...)` call.

(d) `resume_goal` signature `def resume_goal(goal_id: str, req: GoalResumeRequest = GoalResumeRequest()):`; after the `goal.status not in ("ready", "paused")` 409 check and before `_goal_coordinator().start(...)`:

```python
    if req.token_budget is not None:
        if req.token_budget < 1:
            raise HTTPException(status_code=422, detail="token_budget must be >= 1")
        _andromeda.goal_store.set_token_budget(gid, req.token_budget)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/api -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/andromeda_service.py test/api/test_goals_budget_api.py
git commit -m "feat(api): token_budget on goal create and resume"
```

---

### Task 8: PostgreSQL parity

**Files:**
- Create: `core/storage/migrations/versions/v0004_goal_budget.py`
- Modify: `core/goals/postgres_store.py` (`_goal` line 38, `create_goal` line 57, new methods after `set_goal_status` line 82)
- Test: `test/goals/test_postgres_goal_budget.py` (create)

**Interfaces:**
- Produces: `PostgresGoalStore` has the same five new `GoalStore` methods and returns the new `GoalContract` fields.

- [ ] **Step 1: Write the failing tests** — create `test/goals/test_postgres_goal_budget.py` (SQLite engine injected through the constructor's `engine=` seam):

```python
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from core.contracts import GoalContract
from core.goals.postgres_store import PostgresGoalStore

DDL = """CREATE TABLE goals (
    goal_id TEXT PRIMARY KEY, origin TEXT NOT NULL, objective TEXT NOT NULL,
    confidence_threshold REAL NOT NULL, status TEXT NOT NULL, plan_confidence REAL,
    created_at TEXT NOT NULL, token_budget INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0, fallback_used BOOLEAN NOT NULL DEFAULT 0,
    resume_after TEXT, pause_reason TEXT)"""


def _store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pg.db'}")
    with engine.begin() as c:
        c.execute(text(DDL))
    return PostgresGoalStore("postgresql://test/test", engine=engine)


def test_round_trip_and_methods(tmp_path):
    store = _store(tmp_path)
    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.65, token_budget=500)
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 25)
    when = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    store.pause_with_reason(goal.goal_id, "provider_quota", when)
    store.set_fallback_used(goal.goal_id, True)
    got = store.get_goal(goal.goal_id)
    assert got.token_budget == 500 and got.tokens_used == 25
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert got.resume_after == when and got.fallback_used is True

    store.clear_pause(goal.goal_id)
    store.set_token_budget(goal.goal_id, None)
    got = store.get_goal(goal.goal_id)
    assert got.pause_reason is None and got.fallback_used is False
    assert got.token_budget is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest test/goals/test_postgres_goal_budget.py -q`
Expected: FAIL (`AttributeError: add_tokens_used`).

- [ ] **Step 3: Implement**

Create `core/storage/migrations/versions/v0004_goal_budget.py`:

```python
"""Goal token budget, usage and provider-failover pause metadata."""

from alembic import op


revision = "0004_goal_budget"
down_revision = "0003_artifact_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE goals ADD COLUMN token_budget BIGINT")
    op.execute("ALTER TABLE goals ADD COLUMN tokens_used BIGINT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE goals ADD COLUMN fallback_used BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE goals ADD COLUMN resume_after TEXT")
    op.execute("ALTER TABLE goals ADD COLUMN pause_reason TEXT")


def downgrade() -> None:
    for column in ("pause_reason", "resume_after", "fallback_used", "tokens_used", "token_budget"):
        op.execute(f"ALTER TABLE goals DROP COLUMN {column}")
```

In `core/goals/postgres_store.py`:

(a) `_goal`: add to the `GoalContract(...)` call:

```python
            token_budget=row["token_budget"], tokens_used=row["tokens_used"],
            fallback_used=bool(row["fallback_used"]),
            resume_after=_timestamp(row["resume_after"]) if row["resume_after"] else None,
            pause_reason=row["pause_reason"],
```

(b) `create_goal`: add `token_budget` to the column list, `:budget` to VALUES, and `"budget": goal.token_budget` to the params.

(c) new methods after `set_goal_status`:

```python
    def add_tokens_used(self, goal_id: UUID, tokens: int) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE goals SET tokens_used=tokens_used+:n WHERE goal_id=:id"),
                      {"n": tokens, "id": str(goal_id)})

    def set_fallback_used(self, goal_id: UUID, used: bool) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE goals SET fallback_used=:u WHERE goal_id=:id"),
                      {"u": used, "id": str(goal_id)})

    def set_token_budget(self, goal_id: UUID, token_budget: int | None) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE goals SET token_budget=:b WHERE goal_id=:id"),
                      {"b": token_budget, "id": str(goal_id)})

    def pause_with_reason(self, goal_id: UUID, reason: str, resume_after: datetime | None) -> None:
        with self.engine.begin() as c:
            c.execute(
                text("UPDATE goals SET status='paused', pause_reason=:r, resume_after=:t WHERE goal_id=:id"),
                {"r": reason, "t": resume_after.isoformat() if resume_after else None, "id": str(goal_id)},
            )

    def clear_pause(self, goal_id: UUID) -> None:
        with self.engine.begin() as c:
            c.execute(
                text("UPDATE goals SET pause_reason=NULL, resume_after=NULL, fallback_used=FALSE WHERE goal_id=:id"),
                {"id": str(goal_id)},
            )
```

Note: `FALSE` is a valid literal in both PostgreSQL and SQLite ≥ 3.23.

- [ ] **Step 4: Run to verify pass**

Run: `pytest test/goals/test_postgres_goal_budget.py test/core/test_platform_migration.py -q && pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add core/storage/migrations/versions/v0004_goal_budget.py core/goals/postgres_store.py test/goals/test_postgres_goal_budget.py
git commit -m "feat(goals): postgres parity for token budget and failover state"
```

---

## Self-Review

- **Spec coverage:** contract fields (T1), persistence (T2/T8), metering + `LLMQuotaError` + fallback config (T3), failover/pause/resume/budget check (T6), executor + worker (T5), API incl. resume budget (T7), 15-min default delay (T6 constructor), token-cap never auto-resumed (T6 tests), distributed-agents limit unchanged (spec "Known limits").
- **Spec deltas, deliberately:** (1) mechanism lives in `DurableGoalCoordinator` + worker executor, not `GoalRunner` (unreachable from services); (2) `LLMQuotaError` is converted to a `failed/provider_quota` result inside Andromeda because `_execute_node` swallows all exceptions and `failed` otherwise escalates to the review queue; (3) planning tokens (`GoalPlanner`, called in the API process before any task runs) are **not** metered in this plan.
- **Known gap to confirm:** `GoalPlanner` quota errors at `POST /goals` still surface as the existing 502 `planner error`; no failover there.
- **Type consistency:** `model_tier` ("primary"/"fallback") written in T5, read in T6; `pause_reason` literals `token_budget`/`provider_quota` identical across T1, T2, T6; store method names identical in T2, T6, T8.
