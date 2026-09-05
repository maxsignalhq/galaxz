# PostgreSQL migration foundation (SCRUM-46)

The PostgreSQL operational schema and explicit Alembic administration command
are available for development and upgrade testing. The PostgreSQL repositories
mirror durable enqueue, claim, heartbeat, completion, cancellation, recovery,
inspection, goals, reviews, artifacts and task logs. API and worker selection
requires an explicit `GALAXZ_DATABASE_URL` and a current schema; SQLite remains
the local default.

## Schema administration

Install `requirements.txt`. Supply a PostgreSQL URL through `GALAXZ_DATABASE_URL`
in the administrator process environment, then run:

```bash
python -m core.storage.manage upgrade
python -m core.storage.manage check
```

`upgrade` applies the checked-in revision chain in one database transaction and
uses an advisory transaction lock to serialize simultaneous deployment commands.
The connection must have DDL permission in the target database/schema.
`check` reads the version without creating tables or applying migrations. It
rejects an uninitialized, older, newer or divergent schema with an actionable
error. Connection errors do not print database URLs or driver parameters.

Migrations run independently of request startup, following Alembic's
[shared-connection transaction pattern](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).
Runtime repositories call `require_current_schema(connection)` before serving
production requests. Do not call
`migrate()` from a store constructor or API lifecycle hook.

API and worker startup fail closed when `GALAXZ_DATABASE_URL` is set but the
schema is unsupported. This prevents a partially configured deployment from
silently using SQLite for jobs while expecting PostgreSQL state. Local
deployments omit that variable and continue using the explicit SQLite paths.

## Reviewed revision chain

- `0001_operational`: consolidated schema for goals, projects, planned tasks,
  task logs, goal audit events, jobs, attempts, transitions, immutable inputs
  and outputs, reviews and artifact versions. The frozen SQL is packaged with
  Galaxz and never imports live SQLite table definitions.
- `0002_completion`: completion outbox and attempt-to-artifact-version mappings.
  Existing attempt-scoped artifact versions are backfilled into the mapping.
  Old completed jobs are not replayed as new publications.

UUIDs, timestamps and JSON remain text in this initial schema to preserve the
current stores' serialization contracts. SQLite auto-increment keys become
PostgreSQL identity columns, and floating-point values use double precision.
This is a schema baseline, not an automatic importer of local SQLite databases.
Moving populated SQLite deployments and wiring every Postgres repository remain
part of SCRUM-46. The job repository uses `FOR UPDATE SKIP LOCKED` for worker
claims, following [PostgreSQL's queue guidance](https://www.postgresql.org/docs/current/sql-select.html).

An upgrade failure rolls back both DDL and version changes. The operator command
only upgrades or checks; it never automatically downgrades an unknown schema.
Downgrade functions exist for reviewed recovery/testing, but removing revision
2 deletes publication/mapping state and removing revision 1 deletes operational
tables. Restore from a verified backup for production recovery rather than
running a destructive downgrade without a data-preservation plan.

## Isolated verification

```bash
docker compose -f docker-compose.postgres-test.yml run --build --rm migration-tests
docker compose -f docker-compose.postgres-test.yml down
```

This separate Compose project uses PostgreSQL 16, a private network, test-only
credentials and ephemeral database storage. It exposes no host database port
and does not mount application data. Each test creates its own randomly named
schema and cleans up only that schema. CI runs the same command.

Coverage includes fresh/repeated upgrades, an existing populated baseline,
immutable artifact backfill, orphan-reference rejection, unknown versions,
transactional rollback after injected DDL failure, concurrent administrator
processes, and reviewed downgrade/re-upgrade. Ordinary `pytest test` skips the
PostgreSQL cases unless `GALAXZ_TEST_POSTGRES_URL` is explicitly set.
