# Project Review

_Last refreshed: 2026-11-07._

## Current State

The findings from the earlier versions of this report remain resolved:

1. **`test/api/test_andromeda_api.py` stale** — resolved (commit `fb4fe70`).
2. **`confidence_threshold` not honored by the router** — resolved (commit `591a5a2`);
   `_after_execute` prefers the per-task value, the `0.40` failure threshold stays global.
3. **Contract-shape drift vs. `CLAUDE.md`** — resolved; `CLAUDE.md` matches
   `core/contracts/contracts.py`.

Continuous integration on `main` was red for the five merges before 2026-11-07 because of two
tests that only failed on the CI runner (Python 3.11 float summation in
`test_experiments.py`; missing git committer identity in `test_repository_pr_lifecycle.py`).
Both were fixed in PR #22, which also surfaced and fixed a populated-upgrade migration test
that only allowed new columns on `artifact_versions`. All four CI jobs (Python, Prism,
PostgreSQL migrations, Integration containers) pass.

## Shipped Since The Prior Review (2026-08-28)

- **Durable execution** — leased, retryable job queue and worker (`core/jobs/`,
  `services/worker_service.py`); `DurableGoalCoordinator` (`core/goals/coordinator.py`)
  replaces the in-process `GoalRunner`, which is no longer reachable from `services/` and is
  kept only for its tests.
- **Storage** — PostgreSQL stores with explicit Alembic migrations (currently through
  `0005_goal_workspace_root`), object storage for artifacts, backup/restore drills.
  `PostgresGoalStore` now has parity with `GoalStore` (token budget, failover state,
  `workspace_root`).
- **Goal token budget and provider failover** — per-goal metering, budget pause and
  auto-resume, fallback-model failover (PR #20).
- **Secret references** — `${{ secrets.<id> }}` in `quasar.*` tool payloads, resolved only
  during the tool call, scoped to organization, repository and skill, redacted from results
  and errors; `galaxz secret put` (spec `docs/specs/2026-11-07-secret-references-design.md`).
- **Agent platform** — Nebula memory, Quasar MCP tools, Constellation catalog, Wormhole A2A
  gateway, pre-action policy gate, signed scorecards, human-gated skill lessons, per-provider
  LLM limiter, GitHub App / PR workflow, repository registry, per-goal git worktrees.
- **Prism** — containerized (`prism` service in `docker-compose.yml`), Goals and Artifacts
  pages. The image build is exercised by the CI "Integration containers" job.

## Remaining Backlog

- **v2-scope, deferred** — multi-tenancy, user accounts/roles, OAuth/SSO, per-agent auth,
  audit logging, and executing (not just curating) fine-tune training runs.
- **Secrets follow-ups** — no PostgreSQL backend, rotation or listing for the secret store; no
  interpolation of a reference inside a larger string (see the spec's non-goals).
- **Not yet verified end to end** — secret references against a real MCP server and token.

## Coverage Gaps In Existing Tests

1. Normal pytest coverage focuses on isolated units; the deterministic end-to-end
   cross-system handshake lives in the eval harness (`evals/run_evals.py`).
2. Five Orion tests skip without Redis. Nine PostgreSQL migration tests skip unless
   `GALAXZ_TEST_POSTGRES_URL` is set; CI runs them in the "PostgreSQL migrations" job, and
   locally via `docker compose -f docker-compose.postgres-test.yml run --build --rm migration-tests`.
3. Several tests read `config/workspace.yaml`; a local edit that enables the workspace with a
   path that does not exist on the host makes unrelated tests fail. Keep that file at its
   committed environment-variable form, or override it through `GALAXZ_WORKSPACE_*`.
