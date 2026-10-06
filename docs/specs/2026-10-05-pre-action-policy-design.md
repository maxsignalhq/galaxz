# Pre-action authorization (policy gate) — Design

Date: 2026-10-05

## Problem
Skills that act on the outside world (MCP tools via Quasar, remote A2A agents via
Wormhole, code execution) run as soon as Andromeda routes them. `allowed_origins`
limits *who* may use a skill, but there is no way to say "this skill, from this origin,
must not run" or "must be approved by a human first", and no place to enforce it that
every task passes through. `core/security/execution_policy.py` already limits Rigel's
sandbox (commands, environment, paths); it is unrelated to task routing.

## Design
No new task contract. A policy gate is evaluated once per task, as the first node of
Andromeda's routing graph, before skill matching and before any agent runs.

`config/policy.yaml` (`GALAXZ_POLICY_PATH` overrides), ships `rules: []`:

```yaml
rules:
  - skill: "quasar.fs.*"        # fnmatch against the skill id (required)
    origin: "a2a:*"             # fnmatch against TaskContract.origin (default "*")
    action: require_review      # deny | require_review
    reason: "filesystem tools need a human"
```

- Rules are evaluated in order; the first rule matching a skill decides. No match = allow.
  An empty policy allows everything, so behavior is unchanged until rules are added.
- `deny`: the task ends as `no_agent_found` with `failure_reason="policy_denied"` and the
  agent is never run. Wormhole maps this to `TASK_STATE_REJECTED`.
- `require_review`: the task is escalated (`failure_reason="policy_requires_review"`) into
  the existing review queue without running. Its review item carries a `policy_hold`
  record in `agent_output`. **Approving (or accepting) the item issues a single-use grant**
  for exactly that `(origin, skill, payload)`, valid for one hour; the next identical
  submission consumes the grant and proceeds. For a goal task, approval also reruns the
  planned task (instead of marking it complete with no output). Rejecting issues no grant.
- Grants live in SQLite (`POLICY_DB_PATH`, default `data/policy.db`, created lazily on first
  use). Matching is by a SHA-256 digest of the canonical JSON of origin, skill and payload.
- Multiple required skills (legacy `route(required_skills=[...])`): the strictest decision
  wins; each held skill needs its own grant.
- The policy file fails **closed**: a malformed file, unknown key, unknown action or empty
  `skill` raises `PolicyConfigError` at boot, rather than silently running with a weaker
  policy than the operator wrote. A missing file means "no policy".

## Contracts
No change to `TaskContract`, `SkillManifest` or the feedback events. The review item's
free-form `agent_output` gains a `policy_hold` object
`{"origin", "skill", "digest", "reason", "rule_index"}`.

## Testing
Rule matching (glob, order, default origin, strictest-wins), config validation (fail
closed), grant issue/consume (single-use, expiry, wrong origin/skill/payload), the routing
graph (allow, deny, hold, grant consumed, retry path unaffected), and the review API
(approve and accept issue a grant, reject does not, goal tasks rerun).

## Limits
- Policy is evaluated by Andromeda only; an agent reached some other way is not gated.
- A grant authorises a re-submission; it does not execute the held task by itself, so the
  requester (or the goal runner, via rerun) must submit it again.
- Grants and policy are single-node SQLite/YAML, like Nebula; no hot reload (restart to
  change `config/policy.yaml`).
- Conditions beyond skill and origin (payload contents, rate, time of day) are out of scope.

## Decisions made without review
Written while the requester was away; each is easy to change:
1. Two actions only (`deny`, `require_review`); no `allow` rules or per-rule priorities.
2. Approval issues a one-hour single-use grant rather than executing inside the approve
   request, so approval never blocks on a long agent call.
3. Fail-closed config loading, unlike Quasar/Wormhole which skip bad entries, because a
   skipped `deny` rule silently weakens security.
4. Logged at WARNING (not written to `AuditLog`); audit integration is left for v2.
