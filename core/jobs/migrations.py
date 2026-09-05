from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from datetime import timezone


Migration = tuple[Callable[[sqlite3.Connection], None], Callable[[sqlite3.Connection], None]]


def _upgrade_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL,
            backoff_seconds REAL NOT NULL,
            max_backoff_seconds REAL NOT NULL,
            retryable_outcomes_json TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            active_attempt_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            cancellation_requested_at TEXT,
            cancelled_at TEXT
        );

        CREATE TABLE execution_attempts (
            attempt_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            attempt_number INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            input_ref TEXT NOT NULL,
            lease_token TEXT NOT NULL UNIQUE,
            lease_expires_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            outcome TEXT,
            failure_kind TEXT,
            error_code TEXT,
            error TEXT,
            output_ref TEXT,
            UNIQUE(job_id, attempt_number)
        );

        CREATE TABLE job_transitions (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            from_status TEXT,
            to_status TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE job_idempotency (
            idempotency_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
            created_at TEXT NOT NULL
        );

        CREATE TABLE job_tasks (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
            task_json TEXT NOT NULL
        );

        CREATE TABLE job_outputs (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX jobs_claim_order
            ON jobs(status, available_at, priority DESC, created_at);
        CREATE INDEX attempts_active_lease
            ON execution_attempts(job_id, ended_at, lease_expires_at);
        """
    )


def _downgrade_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS job_idempotency;
        DROP TABLE IF EXISTS job_outputs;
        DROP TABLE IF EXISTS job_tasks;
        DROP TABLE IF EXISTS job_transitions;
        DROP TABLE IF EXISTS execution_attempts;
        DROP TABLE IF EXISTS jobs;
        """
    )


def _upgrade_v2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE completion_outbox (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
            attempt_id TEXT NOT NULL UNIQUE REFERENCES execution_attempts(attempt_id),
            created_at TEXT NOT NULL,
            published_at TEXT
        )
        """
    )


def _downgrade_v2(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE completion_outbox")


MIGRATIONS: tuple[Migration, ...] = (
    (_upgrade_v1, _downgrade_v1),
    (_upgrade_v2, _downgrade_v2),
)


def current_version(connection: sqlite3.Connection) -> int:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def upgrade(connection: sqlite3.Connection, target: int | None = None) -> int:
    latest = len(MIGRATIONS)
    target = latest if target is None else target
    if not 0 <= target <= latest:
        raise ValueError(f"migration target must be between 0 and {latest}")

    version = current_version(connection)
    for next_version in range(version + 1, target + 1):
        up, _ = MIGRATIONS[next_version - 1]
        with connection:
            up(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (next_version, datetime.now(timezone.utc).isoformat()),
            )
    return current_version(connection)


def rollback(connection: sqlite3.Connection, target: int = 0) -> int:
    version = current_version(connection)
    if not 0 <= target <= version:
        raise ValueError(f"rollback target must be between 0 and {version}")

    for current in range(version, target, -1):
        _, down = MIGRATIONS[current - 1]
        with connection:
            down(connection)
            connection.execute("DELETE FROM schema_migrations WHERE version = ?", (current,))
    return current_version(connection)
