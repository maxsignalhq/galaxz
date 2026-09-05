from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from core.contracts import AttemptOutcome
from core.contracts import ExecutionAttempt
from core.contracts import Job
from core.contracts import JobStatus
from core.contracts import RetryPolicy
from core.contracts import TaskContract
from core.contracts import validate_job_transition

from .migrations import rollback
from .migrations import upgrade


class InvalidJobState(RuntimeError):
    pass


class LeaseConflict(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _deserialize(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class SqliteJobRepository:
    """Transactional local-mode job storage.

    PostgreSQL DSNs are intentionally rejected: the production implementation
    must use a dedicated backend rather than silently falling back to SQLite.
    """

    def __init__(self, database: str | Path, *, migrate: bool = True) -> None:
        database_string = str(database)
        if database_string.startswith(("postgres://", "postgresql://")):
            raise ValueError(
                "PostgreSQL job storage is not implemented; configure an explicit SQLite path"
            )
        self.database = database_string
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        if migrate:
            connection = self._connect()
            try:
                upgrade(connection)
            finally:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migration_version(self) -> int:
        connection = self._connect()
        try:
            from .migrations import current_version

            return current_version(connection)
        finally:
            connection.close()

    def rollback_migrations(self, target: int = 0) -> int:
        connection = self._connect()
        try:
            return rollback(connection, target)
        finally:
            connection.close()

    def enqueue(
        self,
        *,
        task_id: UUID,
        task: TaskContract | None = None,
        idempotency_key: str,
        priority: int = 0,
        retry_policy: RetryPolicy | None = None,
        now: datetime | None = None,
    ) -> Job:
        retry_policy = retry_policy or RetryPolicy()
        if task is not None and task.task_id != task_id:
            raise ValueError("task_id must match task.task_id")
        now = now or _utc_now()
        candidate = Job(
            task_id=task_id,
            idempotency_key=idempotency_key,
            priority=priority,
            retry_policy=retry_policy,
            created_at=now,
            updated_at=now,
            available_at=now,
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT jobs.*
                FROM job_idempotency
                JOIN jobs USING(job_id)
                WHERE idempotency_key = ?
                """,
                (candidate.idempotency_key,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return self._job_from_row(existing, candidate.idempotency_key)

            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, task_id, status, priority, max_attempts,
                    backoff_seconds, max_backoff_seconds, retryable_outcomes_json,
                    created_at, updated_at, available_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(candidate.job_id),
                    str(candidate.task_id),
                    candidate.status.value,
                    candidate.priority,
                    retry_policy.max_attempts,
                    retry_policy.backoff_seconds,
                    retry_policy.max_backoff_seconds,
                    json.dumps(sorted(retry_policy.retryable_outcomes)),
                    _serialize(now),
                    _serialize(now),
                    _serialize(now),
                ),
            )
            connection.execute(
                "INSERT INTO job_idempotency(idempotency_key, job_id, created_at) VALUES (?, ?, ?)",
                (candidate.idempotency_key, str(candidate.job_id), _serialize(now)),
            )
            if task is not None:
                connection.execute(
                    "INSERT INTO job_tasks(job_id, task_json) VALUES (?, ?)",
                    (str(candidate.job_id), task.model_dump_json()),
                )
            self._record_transition(connection, candidate.job_id, None, JobStatus.queued, "enqueue", now)
            connection.commit()
            return candidate
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_task(self, job_id: UUID) -> TaskContract | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT task_json FROM job_tasks WHERE job_id = ?", (str(job_id),)
            ).fetchone()
            return TaskContract.model_validate_json(row[0]) if row is not None else None
        finally:
            connection.close()

    def get_result(self, job_id: UUID) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT result_json FROM job_outputs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
            return json.loads(row[0]) if row is not None else None
        finally:
            connection.close()

    def get_job(self, job_id: UUID) -> Job | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT jobs.*, job_idempotency.idempotency_key
                FROM jobs JOIN job_idempotency USING(job_id)
                WHERE job_id = ?
                """,
                (str(job_id),),
            ).fetchone()
            return self._job_from_row(row) if row is not None else None
        finally:
            connection.close()

    def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT jobs.*, job_idempotency.idempotency_key
                FROM jobs JOIN job_idempotency USING(job_id)
                WHERE job_idempotency.idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            return self._job_from_row(row) if row is not None else None
        finally:
            connection.close()

    def list_jobs(self, *, limit: int = 50) -> list[Job]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT jobs.*, job_idempotency.idempotency_key
                FROM jobs JOIN job_idempotency USING(job_id)
                ORDER BY created_at DESC, job_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._job_from_row(row) for row in rows]
        finally:
            connection.close()

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> tuple[Job, ExecutionAttempt] | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT jobs.*, job_idempotency.idempotency_key
                FROM jobs JOIN job_idempotency USING(job_id)
                WHERE status = ? AND available_at <= ? AND attempt_count < max_attempts
                ORDER BY priority DESC, created_at, job_id
                LIMIT 1
                """,
                (JobStatus.queued.value, _serialize(now)),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            job_id = UUID(row["job_id"])
            validate_job_transition(JobStatus.queued, JobStatus.running)
            attempt = ExecutionAttempt(
                job_id=job_id,
                attempt_number=row["attempt_count"] + 1,
                worker_id=worker_id,
                input_ref=f"task:{row['task_id']}",
                started_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            updated = connection.execute(
                """
                UPDATE jobs
                SET status = ?, attempt_count = attempt_count + 1,
                    active_attempt_id = ?, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    JobStatus.running.value,
                    str(attempt.attempt_id),
                    _serialize(now),
                    str(job_id),
                    JobStatus.queued.value,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            self._insert_attempt(connection, attempt)
            self._record_transition(
                connection, job_id, JobStatus.queued, JobStatus.running, "claim", now
            )
            connection.commit()
            claimed = self.get_job(job_id)
            assert claimed is not None
            return claimed, attempt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> ExecutionAttempt:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._active_attempt(connection, job_id, lease_token)
            if row is None or _deserialize(row["lease_expires_at"]) <= now:
                raise LeaseConflict("heartbeat requires the active, unexpired lease")
            expiry = now + timedelta(seconds=lease_seconds)
            connection.execute(
                "UPDATE execution_attempts SET lease_expires_at = ? WHERE attempt_id = ?",
                (_serialize(expiry), row["attempt_id"]),
            )
            connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                (_serialize(now), str(job_id)),
            )
            connection.commit()
            return self._attempt_from_row({**dict(row), "lease_expires_at": _serialize(expiry)})
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        output_ref: str,
        result: dict | None = None,
        now: datetime | None = None,
    ) -> Job:
        return self._finish(
            job_id=job_id,
            lease_token=lease_token,
            target=JobStatus.completed,
            outcome=AttemptOutcome.completed,
            output_ref=output_ref,
            error=None,
            result=result,
            now=now,
        )

    def pending_completions(self, limit: int = 100) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT job_id, attempt_id, created_at FROM completion_outbox "
                "WHERE published_at IS NULL ORDER BY created_at LIMIT ?", (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def acknowledge_completion(self, job_id: UUID) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE completion_outbox SET published_at = ? "
                "WHERE job_id = ? AND published_at IS NULL",
                (_serialize(_utc_now()), str(job_id)),
            )
        finally:
            connection.close()

    def fail(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        error: str,
        error_code: str = "permanent",
        failure_kind: str = "execution",
        now: datetime | None = None,
    ) -> Job:
        return self.record_failure(
            job_id=job_id,
            lease_token=lease_token,
            error=error,
            error_code=error_code,
            failure_kind=failure_kind,
            retryable=False,
            now=now,
        )

    def record_failure(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        error: str,
        error_code: str,
        failure_kind: str = "execution",
        retryable: bool = True,
        now: datetime | None = None,
    ) -> Job:
        now = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
            if job_row is None:
                raise KeyError(str(job_id))
            if JobStatus(job_row["status"]) is not JobStatus.running:
                raise InvalidJobState(f"job is {job_row['status']}, not running")
            attempt = self._active_attempt(connection, job_id, lease_token)
            if attempt is None or _deserialize(attempt["lease_expires_at"]) <= now:
                raise LeaseConflict("failure requires the active, unexpired lease")

            retryable_codes = frozenset(json.loads(job_row["retryable_outcomes_json"]))
            should_retry = (
                retryable
                and error_code in retryable_codes
                and job_row["attempt_count"] < job_row["max_attempts"]
            )
            target = JobStatus.queued if should_retry else JobStatus.failed
            validate_job_transition(JobStatus.running, target)
            connection.execute(
                """
                UPDATE execution_attempts
                SET ended_at = ?, outcome = ?, failure_kind = ?, error_code = ?, error = ?
                WHERE attempt_id = ? AND ended_at IS NULL
                """,
                (
                    _serialize(now),
                    AttemptOutcome.failed.value,
                    failure_kind,
                    error_code,
                    error,
                    attempt["attempt_id"],
                ),
            )
            delay = min(
                job_row["backoff_seconds"]
                * (2 ** max(job_row["attempt_count"] - 1, 0)),
                job_row["max_backoff_seconds"],
            )
            available_at = now + timedelta(seconds=delay) if should_retry else now
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, active_attempt_id = NULL, updated_at = ?, available_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    target.value,
                    _serialize(now),
                    _serialize(available_at),
                    str(job_id),
                    JobStatus.running.value,
                ),
            )
            reason = f"retry:{error_code}" if should_retry else f"failed:{error_code}"
            self._record_transition(
                connection, job_id, JobStatus.running, target, reason, now
            )
            connection.commit()
            failed = self.get_job(job_id)
            assert failed is not None
            return failed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cancel(self, *, job_id: UUID, now: datetime | None = None) -> Job:
        now = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)).fetchone()
            if row is None:
                raise KeyError(str(job_id))
            current = JobStatus(row["status"])
            if current is JobStatus.cancelled:
                connection.commit()
                cancelled = self.get_job(job_id)
                assert cancelled is not None
                return cancelled
            validate_job_transition(current, JobStatus.cancelled)
            if current is JobStatus.running:
                connection.execute(
                    """
                    UPDATE execution_attempts
                    SET ended_at = ?, outcome = ?
                    WHERE attempt_id = ? AND ended_at IS NULL
                    """,
                    (_serialize(now), AttemptOutcome.cancelled.value, row["active_attempt_id"]),
                )
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, active_attempt_id = NULL, updated_at = ?,
                    cancellation_requested_at = ?, cancelled_at = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.cancelled.value,
                    _serialize(now),
                    _serialize(now),
                    _serialize(now),
                    str(job_id),
                ),
            )
            self._record_transition(
                connection, job_id, current, JobStatus.cancelled, "cancel", now
            )
            connection.commit()
            cancelled = self.get_job(job_id)
            assert cancelled is not None
            return cancelled
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reclaim_expired(self, *, now: datetime | None = None) -> list[Job]:
        now = now or _utc_now()
        connection = self._connect()
        reclaimed_ids: list[UUID] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT jobs.*, execution_attempts.lease_expires_at
                FROM jobs
                JOIN execution_attempts ON execution_attempts.attempt_id = jobs.active_attempt_id
                WHERE jobs.status = ? AND execution_attempts.ended_at IS NULL
                    AND execution_attempts.lease_expires_at <= ?
                """,
                (JobStatus.running.value, _serialize(now)),
            ).fetchall()
            for row in rows:
                job_id = UUID(row["job_id"])
                terminal = row["attempt_count"] >= row["max_attempts"]
                target = JobStatus.failed if terminal else JobStatus.queued
                validate_job_transition(JobStatus.running, target)
                connection.execute(
                    """
                    UPDATE execution_attempts
                    SET ended_at = ?, outcome = ?
                    WHERE attempt_id = ? AND ended_at IS NULL
                    """,
                    (
                        _serialize(now),
                        AttemptOutcome.lease_expired.value,
                        row["active_attempt_id"],
                    ),
                )
                delay = min(
                    row["backoff_seconds"] * (2 ** max(row["attempt_count"] - 1, 0)),
                    row["max_backoff_seconds"],
                )
                available_at = now if terminal else now + timedelta(seconds=delay)
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, active_attempt_id = NULL, updated_at = ?, available_at = ?
                    WHERE job_id = ?
                    """,
                    (target.value, _serialize(now), _serialize(available_at), str(job_id)),
                )
                self._record_transition(
                    connection, job_id, JobStatus.running, target, "lease_expired", now
                )
                reclaimed_ids.append(job_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return [job for job_id in reclaimed_ids if (job := self.get_job(job_id)) is not None]

    def transitions(self, job_id: UUID) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT from_status, to_status, reason, created_at
                FROM job_transitions WHERE job_id = ? ORDER BY transition_id
                """,
                (str(job_id),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def attempts(self, job_id: UUID) -> list[ExecutionAttempt]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM execution_attempts
                WHERE job_id = ? ORDER BY attempt_number
                """,
                (str(job_id),),
            ).fetchall()
            return [self._attempt_from_row(row) for row in rows]
        finally:
            connection.close()

    def _finish(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        target: JobStatus,
        outcome: AttemptOutcome,
        output_ref: str | None,
        error: str | None,
        result: dict | None,
        now: datetime | None,
    ) -> Job:
        now = now or _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
            if job_row is None:
                raise KeyError(str(job_id))
            current = JobStatus(job_row["status"])
            if current is JobStatus.completed and target is JobStatus.completed:
                prior = connection.execute(
                    """
                    SELECT output_ref FROM execution_attempts
                    WHERE job_id = ? AND lease_token = ? AND outcome = ?
                    """,
                    (str(job_id), str(lease_token), AttemptOutcome.completed.value),
                ).fetchone()
                if prior is not None and prior["output_ref"] == output_ref:
                    persisted = connection.execute(
                        "SELECT result_json FROM job_outputs WHERE job_id = ?", (str(job_id),),
                    ).fetchone()
                    if result is not None and (
                        persisted is None or persisted["result_json"] != json.dumps(result, sort_keys=True)
                    ):
                        raise InvalidJobState("job already has a different persisted result")
                    connection.commit()
                    existing = self.get_job(job_id)
                    assert existing is not None
                    return existing
            if current is not JobStatus.running:
                raise InvalidJobState(f"job is {current.value}, not running")
            attempt = self._active_attempt(connection, job_id, lease_token)
            if attempt is None or _deserialize(attempt["lease_expires_at"]) <= now:
                raise LeaseConflict("completion requires the active, unexpired lease")
            validate_job_transition(current, target)
            connection.execute(
                """
                UPDATE execution_attempts
                SET ended_at = ?, outcome = ?, error = ?, output_ref = ?
                WHERE attempt_id = ? AND ended_at IS NULL
                """,
                (_serialize(now), outcome.value, error, output_ref, attempt["attempt_id"]),
            )
            if result is not None:
                serialized_result = json.dumps(result, sort_keys=True)
                prior_result = connection.execute(
                    "SELECT result_json FROM job_outputs WHERE job_id = ?",
                    (str(job_id),),
                ).fetchone()
                if prior_result is not None and prior_result["result_json"] != serialized_result:
                    raise InvalidJobState("job already has a different persisted result")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO job_outputs(job_id, result_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (str(job_id), serialized_result, _serialize(now)),
                )
                if result.get("artifacts") or result.get("status") == "escalated":
                    task_row = connection.execute(
                        "SELECT 1 FROM job_tasks WHERE job_id = ?", (str(job_id),),
                    ).fetchone()
                    if task_row is None:
                        raise InvalidJobState("completion evidence requires persisted task input")
                    connection.execute(
                        "INSERT INTO completion_outbox(job_id, attempt_id, created_at) VALUES (?, ?, ?)",
                        (str(job_id), attempt["attempt_id"], _serialize(now)),
                    )
            connection.execute(
                """
                UPDATE jobs SET status = ?, active_attempt_id = NULL, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (target.value, _serialize(now), str(job_id), JobStatus.running.value),
            )
            self._record_transition(connection, job_id, current, target, outcome.value, now)
            connection.commit()
            finished = self.get_job(job_id)
            assert finished is not None
            return finished
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _active_attempt(
        connection: sqlite3.Connection, job_id: UUID, lease_token: UUID
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT execution_attempts.*
            FROM execution_attempts
            JOIN jobs ON jobs.active_attempt_id = execution_attempts.attempt_id
            WHERE jobs.job_id = ? AND jobs.status = ?
                AND execution_attempts.lease_token = ? AND execution_attempts.ended_at IS NULL
            """,
            (str(job_id), JobStatus.running.value, str(lease_token)),
        ).fetchone()

    @staticmethod
    def _insert_attempt(connection: sqlite3.Connection, attempt: ExecutionAttempt) -> None:
        connection.execute(
            """
            INSERT INTO execution_attempts(
                attempt_id, job_id, attempt_number, worker_id, input_ref, lease_token,
                lease_expires_at, started_at, ended_at, outcome, failure_kind,
                error_code, error, output_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(attempt.attempt_id),
                str(attempt.job_id),
                attempt.attempt_number,
                attempt.worker_id,
                attempt.input_ref,
                str(attempt.lease_token),
                _serialize(attempt.lease_expires_at),
                _serialize(attempt.started_at),
                _serialize(attempt.ended_at),
                attempt.outcome.value if attempt.outcome else None,
                attempt.failure_kind,
                attempt.error_code,
                attempt.error,
                attempt.output_ref,
            ),
        )

    @staticmethod
    def _record_transition(
        connection: sqlite3.Connection,
        job_id: UUID,
        current: JobStatus | None,
        target: JobStatus,
        reason: str,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO job_transitions(job_id, from_status, to_status, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(job_id),
                current.value if current is not None else None,
                target.value,
                reason,
                _serialize(now),
            ),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row, idempotency_key: str | None = None) -> Job:
        key = idempotency_key or row["idempotency_key"]
        return Job(
            job_id=UUID(row["job_id"]),
            task_id=UUID(row["task_id"]),
            status=JobStatus(row["status"]),
            priority=row["priority"],
            idempotency_key=key,
            retry_policy=RetryPolicy(
                max_attempts=row["max_attempts"],
                backoff_seconds=row["backoff_seconds"],
                max_backoff_seconds=row["max_backoff_seconds"],
                retryable_outcomes=tuple(json.loads(row["retryable_outcomes_json"])),
            ),
            created_at=_deserialize(row["created_at"]),
            updated_at=_deserialize(row["updated_at"]),
            available_at=_deserialize(row["available_at"]),
            cancellation_requested_at=_deserialize(row["cancellation_requested_at"]),
            cancelled_at=_deserialize(row["cancelled_at"]),
        )

    @staticmethod
    def _attempt_from_row(row: dict | sqlite3.Row) -> ExecutionAttempt:
        return ExecutionAttempt(
            attempt_id=UUID(row["attempt_id"]),
            job_id=UUID(row["job_id"]),
            attempt_number=row["attempt_number"],
            worker_id=row["worker_id"],
            input_ref=row["input_ref"],
            lease_token=UUID(row["lease_token"]),
            lease_expires_at=_deserialize(row["lease_expires_at"]),
            started_at=_deserialize(row["started_at"]),
            ended_at=_deserialize(row["ended_at"]),
            outcome=AttemptOutcome(row["outcome"]) if row["outcome"] else None,
            failure_kind=row["failure_kind"],
            error_code=row["error_code"],
            error=row["error"],
            output_ref=row["output_ref"],
        )
