# Job storage operations

Galaxz v1 provides `SqliteJobRepository` for deterministic single-process and
local deployments. It creates versioned job, execution-attempt, transition, and
idempotency tables and applies migrations when the repository starts.

The repository also stores the immutable task input and the single accepted
result. A completion is committed in the same transaction as its attempt and
state transition. Repeated delivery of the same completion is harmless, while
a stale lease can never replace the accepted result.

SQLite operations use `BEGIN IMMEDIATE`, compare the current state during each
write, and store the attempt plus its job transition in one transaction. This
prevents two local workers from claiming the same queued job. Expired leases are
closed and either requeued with bounded exponential backoff or failed after the
configured maximum attempts.

## Worker runtime

`services/worker_service.py` is the dedicated execution process. It claims
persisted jobs, invokes the same `Andromeda.route(TaskContract)` path used by
the synchronous API, renews its lease on a configurable heartbeat, and records
the worker and attempt IDs in structured log context. The safe default is one
concurrent job per worker.

The worker stops taking new claims before it drains active attempts during a
graceful shutdown. If a process is terminated, another worker reclaims its job
after the lease expires. Retryable failures use bounded exponential backoff;
permanent and confidence failures retain distinct metadata on each attempt.

Configuration:

- `JOB_DB_PATH` (default `data/jobs.db`)
- `WORKER_ID` (default container hostname)
- `WORKER_CONCURRENCY` (default `1`)
- `WORKER_LEASE_SECONDS` (default `30`)
- `WORKER_HEARTBEAT_SECONDS` (default `10`)
- `WORKER_POLL_SECONDS` (default `0.25`)

## API migration path

`POST /task` remains available for synchronous callers. Durable callers submit
the same task fields to `POST /jobs`, plus a required `idempotency_key`, and
receive HTTP 202 with a durable `job_id`. Poll `GET /jobs/{job_id}` for state,
attempt history, transitions, and the accepted result. `POST
/jobs/{job_id}/cancel` is authenticated by the same API-key middleware and is
idempotent. Prism's Task Queue shows durable states and exposes cancellation
for queued or running jobs.

Production PostgreSQL support is a separate Phase 2 deliverable. Passing a
`postgres://` or `postgresql://` DSN currently fails immediately; Galaxz never
silently runs the SQLite concurrency model against a production DSN. The future
PostgreSQL repository must preserve these contracts and use row locking (for
example, `FOR UPDATE SKIP LOCKED`) plus database migrations reviewed for both
upgrade and rollback.

The [PostgreSQL migration foundation](postgres-migrations.md) now provides
explicit Alembic upgrade/check commands and an isolated PostgreSQL test suite.
Runtime repository switching and migration of existing SQLite data remain
unfinished; the schema administration command does not enable production mode.
