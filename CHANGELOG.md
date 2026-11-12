# Changelog

All notable changes to Galaxz are documented here. This file follows a
release-oriented format; entries under **Unreleased** have not been tagged or
published yet.

## Unreleased — production-readiness increment

This increment contains the substantial post-v1 foundation work completed in
the working tree. It is intended to be reviewed before the next GitHub push.

### Added

- Durable job contracts and persistence with queued, running, retry, lease,
  cancellation, recovery, attempt history, and idempotent completion states.
- Worker service with lease heartbeats, recovery, retry handling, and
  PostgreSQL/SQLite repository selection.
- Goal/project hierarchy with dependency-aware durable execution, pause/resume,
  review gating, result substitution, and Prism goal visibility.
- Per-goal token budgets with usage metering, budget pause/resume, and provider
  quota failover to a fallback model (worker, coordinator, API, SQLite and
  PostgreSQL stores).
- Audit logging: every state-changing or rejected API request and every policy
  denial/hold is written to a hash-chained, tamper-evident log (`GALAXZ_AUDIT_DB`),
  readable at `GET /audit/events`, verifiable with `GET /audit/verify` and
  `galaxz audit verify`. Safe for concurrent threads and processes.
- Accounts and roles (phase A): users and expiring, revocable API tokens in the `default`
  organization with `viewer`, `operator`, `reviewer` and `admin` roles enforced on every route
  (undeclared routes require `admin`); `GET /auth/me`; `galaxz admin ...` management commands;
  fine-tune and lesson approvals are attributed to the authenticated user. Migration
  `0006_accounts`. `GALAXZ_API_KEY` keeps working as an administrator.
- Tenant scoping (accounts phase B1): goals and jobs carry an `organization_id` (migration
  `0007_organization_scope`; existing rows land in `default`), taken from the authenticated principal.
  Another organization's goal or job is reported as 404. Job idempotency keys are namespaced per
  organization. **Behaviour change:** `GET /status`, `/agents`, `/tasks/recent`, `/tasks/stats` and
  `/review/queue` no longer answer unauthenticated requests; they need the `read` permission (health,
  liveness and readiness stay open). Organizations cannot be created yet (phase B2).
- Tenant scoping (accounts phase B2a): the task log and review queue carry `organization_id` (migration
  `0008_review_task_scope`); `/task`, `/review/queue*`, `/tasks/*`, `/status` and task feedback only see the
  caller's organization. Fixes two PostgreSQL bugs in `PostgresTaskLog.write` and
  `PostgresReviewQueue.get_stats`.
- Tenant scoping (accounts phase B2b): artifacts (migration `0009_artifact_scope`), Nebula memory, policy grants and
  the repository registry are per organization, and `galaxz admin org-create` / `org-list` / `user-create
  --organization` make a second organization possible. A repository belongs to one organization; GitHub pull-request
  and check-run calls need the repository registered to the caller's organization, and installation listings are
  `default`-only. **Behaviour change:** the artifact routes no longer read `organization_id` from the query string or
  body; it comes from the authenticated principal.
- Secret references: `${{ secrets.<id> }}` in a `quasar.*` tool payload is resolved
  only while the tool runs (scoped to organization, repository and skill) and
  redacted from results and errors, so plaintext never reaches the goal, job,
  task-log or review stores. Create secrets with `galaxz secret put`.
- PostgreSQL schema administration with explicit Alembic migrations, advisory
  migration locking, populated-database upgrade coverage, and fail-closed
  schema compatibility checks.
- PostgreSQL repositories for jobs, goals, reviews, artifacts, and task logs;
  SQLite remains the explicit local-mode backend.
- Pluggable local filesystem and S3-compatible object storage for artifacts,
  including immutable metadata, hashes, size limits, scope checks, orphan
  cleanup, and atomic publication behavior.
- Configurable lifecycle policies, portable export packages with manifests and
  SHA-256 verification, retention purge/dry-run support, encrypted backup
  wrapper, and clean-environment restore drill.
- Repository registration with provider, owner, name, and installation scope;
  access checks; immutable Git base-revision resolution; and goal bindings that
  persist the resolved commit SHA.
- Per-goal Git worktrees and branches rooted at the pinned base revision,
  guarded cleanup, workspace provenance metadata, canonical binary-safe diffs,
  and provenance commits.
- GitHub workflow primitives for evidence-linked pull requests, validation
  check runs, signed webhook intake, and idempotent pull-request lifecycle
  reconciliation.
- GitHub App authentication for installation/repository selection and
  short-lived in-memory installation tokens with least-privilege permissions.
- Integration and contract environments for Docker, PostgreSQL migration and
  repository checks, crash recovery, completion publication, and OpenAPI
  regression verification.

### Changed

- API and worker startup now validate the explicit production schema and use the
  configured PostgreSQL repositories instead of silently splitting state.
- Completion publication is transactional and replayable: job output, artifact
  versions, review records, and attempt references remain consistent across
  retries and service restarts.
- Prism task and goal views now expose durable execution and artifact evidence.
- The OpenAPI regression contract and production-readiness documentation now
  reflect the expanded API and operational model.
- GitHub workflow endpoints now fail closed when integration credentials are not
  configured and verify webhook signatures before processing deliveries.

### Verification

- Local test suite: **251 passed, 14 skipped**.
- Isolated PostgreSQL migration/repository suite: **20 passed**.
- Python compilation and `git diff --check` pass.
- Encrypted backup and clean-environment restore drill smoke test pass.

### Known limitations before publication

- Remote pull-request creation, disposable non-root execution,
  network/resource policy enforcement, identity/RBAC,
  observability, and pilot workflows remain planned Phase 2/3 work.
- Phase 4 tenant isolation, hosted scale, billing, enterprise SSO, and HA/DR
  launch controls remain explicitly future-scope.
- The working tree includes pre-existing uncommitted changes from earlier
  increments; review the complete diff before creating a release tag.

## v1.0.0 — Initial Public Release

See [RELEASE.md](RELEASE.md) for the original v1.0.0 release notes.
