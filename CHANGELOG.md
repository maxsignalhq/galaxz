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

### Verification

- Local test suite: **251 passed, 14 skipped**.
- Isolated PostgreSQL migration/repository suite: **20 passed**.
- Python compilation and `git diff --check` pass.
- Encrypted backup and clean-environment restore drill smoke test pass.

### Known limitations before publication

- GitHub App authentication, remote pull-request creation, disposable
  non-root execution, network/resource policy enforcement, identity/RBAC,
  observability, and pilot workflows remain planned Phase 2/3 work.
- Phase 4 tenant isolation, hosted scale, billing, enterprise SSO, and HA/DR
  launch controls remain explicitly future-scope.
- The working tree includes pre-existing uncommitted changes from earlier
  increments; review the complete diff before creating a release tag.

## v1.0.0 — Initial Public Release

See [RELEASE.md](RELEASE.md) for the original v1.0.0 release notes.
