"""PostgreSQL durable-job repository.

The implementation intentionally mirrors the SQLite repository's public
operations while using row locks for claims and transactional completion.
Schema creation is owned by ``core.storage.manage``; this class never runs DDL.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.contracts import AttemptOutcome, ExecutionAttempt, Job, JobStatus, RetryPolicy, TaskContract
from core.contracts import validate_job_transition

from .repository import InvalidJobState, LeaseConflict


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class PostgresJobRepository:
    """Transactional job storage for a migrated PostgreSQL database."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        if not database_url.startswith(("postgres://", "postgresql://", "postgresql+")):
            raise ValueError("PostgresJobRepository requires a PostgreSQL URL")
        self.database = database_url
        self.engine = engine or create_engine(database_url, pool_pre_ping=True, hide_parameters=True)

    def close(self) -> None:
        self.engine.dispose()

    def migration_version(self) -> str | None:
        with self.engine.connect() as c:
            return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()

    @staticmethod
    def _job(row) -> Job:
        return Job(
            job_id=UUID(row["job_id"]), task_id=UUID(row["task_id"]), status=JobStatus(row["status"]),
            priority=row["priority"], idempotency_key=row["idempotency_key"],
            retry_policy=RetryPolicy(max_attempts=row["max_attempts"], backoff_seconds=row["backoff_seconds"],
                max_backoff_seconds=row["max_backoff_seconds"],
                retryable_outcomes=tuple(json.loads(row["retryable_outcomes_json"]))),
            created_at=_timestamp(row["created_at"]), updated_at=_timestamp(row["updated_at"]), available_at=_timestamp(row["available_at"]),
            cancellation_requested_at=_timestamp(row["cancellation_requested_at"]), cancelled_at=_timestamp(row["cancelled_at"]),
        )

    @staticmethod
    def _attempt(row) -> ExecutionAttempt:
        return ExecutionAttempt(
            attempt_id=UUID(row["attempt_id"]), job_id=UUID(row["job_id"]), attempt_number=row["attempt_number"],
            worker_id=row["worker_id"], input_ref=row["input_ref"], lease_token=UUID(row["lease_token"]),
            lease_expires_at=_timestamp(row["lease_expires_at"]), started_at=_timestamp(row["started_at"]), ended_at=_timestamp(row["ended_at"]),
            outcome=AttemptOutcome(row["outcome"]) if row["outcome"] else None,
            failure_kind=row["failure_kind"], error_code=row["error_code"], error=row["error"],
            output_ref=row["output_ref"],
        )

    def enqueue(self, *, task_id: UUID, task: TaskContract | None = None, idempotency_key: str,
                priority: int = 0, retry_policy: RetryPolicy | None = None, now: datetime | None = None) -> Job:
        if task is not None and task.task_id != task_id:
            raise ValueError("task_id must match task.task_id")
        now = now or _now(); policy = retry_policy or RetryPolicy(); candidate = Job(
            task_id=task_id, idempotency_key=idempotency_key, priority=priority, retry_policy=policy,
            created_at=now, updated_at=now, available_at=now)
        with self.engine.begin() as c:
            existing = c.execute(text("""SELECT j.*, i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id)
                WHERE i.idempotency_key=:key"""), {"key": idempotency_key}).mappings().first()
            if existing: return self._job(existing)
            c.execute(text("""INSERT INTO jobs(job_id,task_id,status,priority,max_attempts,backoff_seconds,max_backoff_seconds,
                retryable_outcomes_json,created_at,updated_at,available_at) VALUES
                (:id,:task,:status,:priority,:max,:backoff,:maxbackoff,:outcomes,:created,:updated,:available)"""), {
                "id": str(candidate.job_id), "task": str(task_id), "status": candidate.status.value, "priority": priority,
                "max": policy.max_attempts, "backoff": policy.backoff_seconds, "maxbackoff": policy.max_backoff_seconds,
                "outcomes": json.dumps(sorted(policy.retryable_outcomes)), "created": now, "updated": now, "available": now})
            c.execute(text("INSERT INTO job_idempotency(idempotency_key,job_id,created_at) VALUES (:key,:id,:now)"),
                      {"key": idempotency_key, "id": str(candidate.job_id), "now": now})
            if task is not None:
                c.execute(text("INSERT INTO job_tasks(job_id,task_json) VALUES (:id,:task)"), {"id": str(candidate.job_id), "task": task.model_dump_json()})
            c.execute(text("INSERT INTO job_transitions(job_id,from_status,to_status,reason,created_at) VALUES (:id,NULL,:to,'enqueue',:now)"), {"id": str(candidate.job_id), "to": JobStatus.queued.value, "now": now})
        return candidate

    def get_task(self, job_id: UUID) -> TaskContract | None:
        with self.engine.connect() as c:
            value = c.execute(text("SELECT task_json FROM job_tasks WHERE job_id=:id"), {"id": str(job_id)}).scalar_one_or_none()
        return TaskContract.model_validate_json(value) if value else None

    def get_result(self, job_id: UUID) -> dict | None:
        with self.engine.connect() as c:
            value = c.execute(text("SELECT result_json FROM job_outputs WHERE job_id=:id"), {"id": str(job_id)}).scalar_one_or_none()
        return json.loads(value) if value else None

    def get_job(self, job_id: UUID) -> Job | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT j.*, i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id) WHERE j.job_id=:id"), {"id": str(job_id)}).mappings().first()
        return self._job(row) if row else None

    def get_job_by_idempotency_key(self, key: str) -> Job | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT j.*, i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id) WHERE i.idempotency_key=:key"), {"key": key}).mappings().first()
        return self._job(row) if row else None

    def list_jobs(self, *, limit: int = 50) -> list[Job]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT j.*, i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id) ORDER BY created_at DESC, job_id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
        return [self._job(row) for row in rows]

    def claim(self, *, worker_id: str, lease_seconds: float, now: datetime | None = None):
        now = now or _now()
        with self.engine.begin() as c:
            row = c.execute(text("""SELECT j.*, i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id)
                WHERE j.status='queued' AND j.available_at::timestamptz <= :now AND j.attempt_count < j.max_attempts
                ORDER BY j.priority DESC,j.created_at,j.job_id LIMIT 1 FOR UPDATE SKIP LOCKED"""), {"now": now}).mappings().first()
            if not row: return None
            job_id = UUID(row["job_id"]); attempt = ExecutionAttempt(job_id=job_id, attempt_number=row["attempt_count"] + 1,
                worker_id=worker_id, input_ref=f"task:{row['task_id']}", started_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds))
            validate_job_transition(JobStatus.queued, JobStatus.running)
            c.execute(text("UPDATE jobs SET status='running',attempt_count=attempt_count+1,active_attempt_id=:attempt,updated_at=:now WHERE job_id=:id"), {"attempt": str(attempt.attempt_id), "now": now, "id": str(job_id)})
            c.execute(text("""INSERT INTO execution_attempts(attempt_id,job_id,attempt_number,worker_id,input_ref,lease_token,lease_expires_at,started_at)
                VALUES (:attempt,:job,:number,:worker,:input,:token,:expires,:started)"""), {"attempt": str(attempt.attempt_id), "job": str(job_id), "number": attempt.attempt_number, "worker": worker_id, "input": attempt.input_ref, "token": str(attempt.lease_token), "expires": attempt.lease_expires_at, "started": now})
            c.execute(text("INSERT INTO job_transitions(job_id,from_status,to_status,reason,created_at) VALUES (:id,'queued','running','claim',:now)"), {"id": str(job_id), "now": now})
            row = dict(row); row.update(status="running", attempt_count=row["attempt_count"] + 1)
        return self._job(row), attempt

    def heartbeat(self, *, job_id: UUID, lease_token: UUID, lease_seconds: float, now: datetime | None = None):
        now = now or _now(); expiry = now + timedelta(seconds=lease_seconds)
        with self.engine.begin() as c:
            row = c.execute(text("SELECT a.* FROM execution_attempts a JOIN jobs j ON j.active_attempt_id=a.attempt_id WHERE j.job_id=:id AND j.status='running' AND a.lease_token=:token AND a.ended_at IS NULL FOR UPDATE"), {"id": str(job_id), "token": str(lease_token)}).mappings().first()
            if not row or _timestamp(row["lease_expires_at"]) <= now: raise LeaseConflict("heartbeat requires the active, unexpired lease")
            c.execute(text("UPDATE execution_attempts SET lease_expires_at=:expiry WHERE attempt_id=:id"), {"expiry": expiry, "id": row["attempt_id"]})
            row = dict(row); row["lease_expires_at"] = expiry
        return self._attempt(row)

    def complete(self, *, job_id: UUID, lease_token: UUID, output_ref: str, result: dict | None = None, now: datetime | None = None) -> Job:
        now = now or _now()
        with self.engine.begin() as c:
            job = c.execute(text("SELECT j.*,i.idempotency_key FROM jobs j JOIN job_idempotency i USING(job_id) WHERE j.job_id=:id FOR UPDATE"), {"id": str(job_id)}).mappings().first()
            if not job or JobStatus(job["status"]) is not JobStatus.running: raise InvalidJobState("job is not running")
            attempt = c.execute(text("SELECT * FROM execution_attempts WHERE attempt_id=:id AND lease_token=:token AND ended_at IS NULL FOR UPDATE"), {"id": job["active_attempt_id"], "token": str(lease_token)}).mappings().first()
            if not attempt or _timestamp(attempt["lease_expires_at"]) <= now: raise LeaseConflict("completion requires the active, unexpired lease")
            if result is not None:
                c.execute(text("INSERT INTO job_outputs(job_id,result_json,created_at) VALUES (:id,:result,:now) ON CONFLICT(job_id) DO UPDATE SET result_json=EXCLUDED.result_json"), {"id": str(job_id), "result": json.dumps(result, sort_keys=True), "now": now})
            c.execute(text("UPDATE execution_attempts SET ended_at=:now,outcome='completed',output_ref=:ref WHERE attempt_id=:id"), {"now": now, "ref": output_ref, "id": attempt["attempt_id"]})
            c.execute(text("UPDATE jobs SET status='completed',active_attempt_id=NULL,updated_at=:now WHERE job_id=:id"), {"now": now, "id": str(job_id)})
            c.execute(text("INSERT INTO job_transitions(job_id,from_status,to_status,reason,created_at) VALUES (:id,'running','completed','completed',:now)"), {"id": str(job_id), "now": now})
        return self.get_job(job_id)

    def cancel(self, *, job_id: UUID, now: datetime | None = None) -> Job:
        now = now or _now()
        with self.engine.begin() as c:
            row = c.execute(text("SELECT * FROM jobs WHERE job_id=:id FOR UPDATE"), {"id": str(job_id)}).mappings().first()
            if not row: raise KeyError(str(job_id))
            if row["status"] == "cancelled": return self.get_job(job_id)
            if row["status"] == "running": c.execute(text("UPDATE execution_attempts SET ended_at=:now,outcome='cancelled' WHERE attempt_id=:id"), {"now": now, "id": row["active_attempt_id"]})
            c.execute(text("UPDATE jobs SET status='cancelled',active_attempt_id=NULL,updated_at=:now,cancellation_requested_at=:now,cancelled_at=:now WHERE job_id=:id"), {"now": now, "id": str(job_id)})
            c.execute(text("INSERT INTO job_transitions(job_id,from_status,to_status,reason,created_at) VALUES (:id,:from,'cancelled','cancel',:now)"), {"id": str(job_id), "from": row["status"], "now": now})
        return self.get_job(job_id)

    def transitions(self, job_id: UUID) -> list[dict]:
        with self.engine.connect() as c: return [dict(r) for r in c.execute(text("SELECT from_status,to_status,reason,created_at FROM job_transitions WHERE job_id=:id ORDER BY transition_id"), {"id": str(job_id)}).mappings()]

    def attempts(self, job_id: UUID) -> list[ExecutionAttempt]:
        with self.engine.connect() as c: rows = c.execute(text("SELECT * FROM execution_attempts WHERE job_id=:id ORDER BY attempt_number"), {"id": str(job_id)}).mappings().all()
        return [self._attempt(r) for r in rows]

    def pending_completions(self, limit: int = 100) -> list[dict]:
        with self.engine.connect() as c: return [dict(r) for r in c.execute(text("SELECT job_id,attempt_id,created_at FROM completion_outbox WHERE published_at IS NULL ORDER BY created_at LIMIT :limit"), {"limit": limit}).mappings()]

    def acknowledge_completion(self, job_id: UUID) -> None:
        with self.engine.begin() as c: c.execute(text("UPDATE completion_outbox SET published_at=:now WHERE job_id=:id AND published_at IS NULL"), {"now": _now(), "id": str(job_id)})

    def reclaim_expired(self, *, now: datetime | None = None) -> list[Job]:
        now = now or _now(); ids = []
        with self.engine.begin() as c:
            rows = c.execute(text("SELECT j.* FROM jobs j JOIN execution_attempts a ON a.attempt_id=j.active_attempt_id WHERE j.status='running' AND a.ended_at IS NULL AND a.lease_expires_at::timestamptz <= :now FOR UPDATE SKIP LOCKED"), {"now": now}).mappings().all()
            for row in rows:
                target = "failed" if row["attempt_count"] >= row["max_attempts"] else "queued"; ids.append(UUID(row["job_id"]))
                c.execute(text("UPDATE execution_attempts SET ended_at=:now,outcome='lease_expired' WHERE attempt_id=:id"), {"now": now, "id": row["active_attempt_id"]})
                c.execute(text("UPDATE jobs SET status=:target,active_attempt_id=NULL,updated_at=:now,available_at=:now WHERE job_id=:id"), {"target": target, "now": now, "id": row["job_id"]})
                c.execute(text("INSERT INTO job_transitions(job_id,from_status,to_status,reason,created_at) VALUES (:id,'running',:target,'lease_expired',:now)"), {"id": row["job_id"], "target": target, "now": now})
        return [self.get_job(i) for i in ids]
