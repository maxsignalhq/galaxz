# Project Review

_Last refreshed: 2026-08-28._

## Current State

The three findings in the prior version of this report are all resolved:

1. **`test/api/test_andromeda_api.py` stale** — resolved. The suite was already brought in
   line with the current FastAPI service (fixed `/health` assertions, bearer-auth headers on
   protected write endpoints) in commit `fb4fe70`. Focused run today: `10 passed`.
2. **`confidence_threshold` not honored by the router** — resolved in commit `591a5a2`.
   `AndromedaState` now carries `confidence_threshold`, `Andromeda.route()` threads
   `TaskContract.confidence_threshold` into it, and `_after_execute` prefers the per-task
   value over the agent's global completion default (falling back to it when absent). The
   `0.40` failure threshold stays global by design. Covered by
   `test/agents/test_andromeda_confidence_threshold.py`.
3. **Contract-shape drift vs. `CLAUDE.md`** — resolved. `CLAUDE.md`'s "Three Core Contracts"
   section now matches `core/contracts/contracts.py` (`origin` / `skill` /
   `confidence_threshold`, not the retired `type` / `context` / `priority` / `origin_agent`).
   No other checked-in doc referenced the stale shape.

## Shipped Since Prior Review

- **Artifact store** (PR #1): `core/artifacts/store.py` `ArtifactStore` records every produced
  artifact with versioned history; `Andromeda.route()` writes through it; the Andromeda
  service exposes `GET /artifacts`, `GET /artifacts/history`, `GET /artifacts/diff`, and
  `POST /artifacts/rollback`.
- **pytest collection error** fixed: the `rigel.skill.test_writing` entrypoint was renamed
  (`agents/rigel/skills/write_tests.py::write_tests`) so pytest no longer tries to collect it
  as a test. Full suite: `130 passed, 5 skipped`.

## Remaining Backlog

Tracked in `CLAUDE.md`'s priority list and `RELEASE.md` "What's Next":

- **Goal/project hierarchy** — LLM-planned `Goal` → `Project` → `Task` DAG with dependency-
  ordered execution, review-queue escalation on failure, and status rollup. Design spec:
  `docs/superpowers/specs/2026-08-28-goal-project-hierarchy-design.md`.
- **Prism containerization** — Dockerfile + `prism` service in `docker-compose.yml`,
  env-configurable API proxy target.
- **Artifact-store operator UI** — a Prism page over the `/artifacts/*` endpoints.
- **v2-scope, deferred** — multi-tenancy, user accounts/roles, OAuth/SSO, per-agent auth,
  audit logging, and executing (not just curating) fine-tune training runs.

## Coverage Gaps In Existing Tests

Unchanged from the prior review:

1. Normal pytest coverage focuses on isolated units; the deterministic end-to-end
   cross-system handshake lives only in the eval harness (`evals/run_evals.py`).
2. Redis-backed end-to-end execution is skipped in normal local runs.
