import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from core.contracts import JobStatus
from core.contracts import RetryPolicy
from core.contracts import TaskContract
from core.contracts.contracts import utc_now
from core.jobs import InvalidJobState
from core.jobs import LeaseConflict
from core.jobs import SqliteJobRepository


def test_migration_upgrade_and_rollback(tmp_path) -> None:
    database = tmp_path / "jobs.db"
    repository = SqliteJobRepository(database)

    assert repository.migration_version() == 2
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "jobs",
        "execution_attempts",
        "job_transitions",
        "job_idempotency",
    } <= tables

    assert repository.rollback_migrations() == 0
    with sqlite3.connect(database) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "jobs" not in remaining


def test_enqueue_claim_heartbeat_and_complete_are_persisted(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(
        task_id=uuid4(),
        idempotency_key="request-1",
        priority=10,
        now=now,
    )

    claimed = repository.claim(worker_id="worker-a", lease_seconds=30, now=now)
    assert claimed is not None
    running, attempt = claimed
    assert running.status is JobStatus.running

    heartbeat = repository.heartbeat(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        lease_seconds=60,
        now=now + timedelta(seconds=1),
    )
    assert heartbeat.lease_expires_at == now + timedelta(seconds=61)

    completed = repository.complete(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        output_ref="artifact://result/1",
        now=now + timedelta(seconds=2),
    )
    assert completed.status is JobStatus.completed
    assert [item["to_status"] for item in repository.transitions(job.job_id)] == [
        "queued",
        "running",
        "completed",
    ]


def test_duplicate_enqueue_returns_existing_job(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    first = repository.enqueue(task_id=uuid4(), idempotency_key="same-key")
    second = repository.enqueue(task_id=uuid4(), idempotency_key="same-key")

    assert second == first


def test_enqueue_persists_task_input_and_completed_result_once(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    task = TaskContract(
        origin="api",
        skill="rigel.skill.code_generation",
        payload={"spec": "hello"},
        confidence_threshold=0.65,
    )
    job = repository.enqueue(
        task_id=task.task_id,
        task=task,
        idempotency_key="durable-task",
    )
    claimed = repository.claim(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    _, attempt = claimed

    first = repository.complete(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        output_ref=f"job-result:{job.job_id}",
        result={"status": "complete", "value": 1},
    )
    duplicate = repository.complete(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        output_ref=f"job-result:{job.job_id}",
        result={"status": "complete", "value": 1},
    )

    assert duplicate == first
    assert repository.get_task(job.job_id) == task
    assert repository.get_result(job.job_id) == {"status": "complete", "value": 1}


def test_only_one_concurrent_worker_claims_a_job(tmp_path) -> None:
    database = tmp_path / "jobs.db"
    repository = SqliteJobRepository(database)
    job = repository.enqueue(task_id=uuid4(), idempotency_key="concurrent")

    def claim(worker_id: str):
        return SqliteJobRepository(database).claim(
            worker_id=worker_id,
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-a", "worker-b"]))

    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    assert claimed[0][0].job_id == job.job_id


def test_completion_requires_the_active_unexpired_lease(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(task_id=uuid4(), idempotency_key="lease", now=now)
    claimed = repository.claim(worker_id="worker-a", lease_seconds=1, now=now)
    assert claimed is not None
    _, attempt = claimed

    with pytest.raises(LeaseConflict):
        repository.complete(
            job_id=job.job_id,
            lease_token=uuid4(),
            output_ref="artifact://wrong-worker",
            now=now,
        )
    with pytest.raises(LeaseConflict):
        repository.complete(
            job_id=job.job_id,
            lease_token=attempt.lease_token,
            output_ref="artifact://late",
            now=now + timedelta(seconds=2),
        )


def test_reclaim_requeues_then_exhausts_retry_policy(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(
        task_id=uuid4(),
        idempotency_key="retry",
        retry_policy=RetryPolicy(
            max_attempts=2,
            backoff_seconds=0,
            max_backoff_seconds=0,
        ),
        now=now,
    )
    first = repository.claim(worker_id="worker-a", lease_seconds=1, now=now)
    assert first is not None

    reclaimed = repository.reclaim_expired(now=now + timedelta(seconds=2))
    assert reclaimed[0].status is JobStatus.queued
    second = repository.claim(
        worker_id="worker-b", lease_seconds=1, now=now + timedelta(seconds=2)
    )
    assert second is not None

    exhausted = repository.reclaim_expired(now=now + timedelta(seconds=4))
    assert exhausted[0].status is JobStatus.failed
    assert repository.claim(worker_id="worker-c", lease_seconds=1) is None
    assert repository.get_job(job.job_id).status is JobStatus.failed


def test_terminal_job_cannot_return_to_running(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(task_id=uuid4(), idempotency_key="terminal", now=now)
    claimed = repository.claim(worker_id="worker-a", lease_seconds=30, now=now)
    assert claimed is not None
    _, attempt = claimed
    repository.complete(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        output_ref="artifact://done",
        now=now + timedelta(seconds=1),
    )

    assert repository.claim(worker_id="worker-b", lease_seconds=30) is None
    with pytest.raises(InvalidJobState):
        repository.complete(
            job_id=job.job_id,
            lease_token=attempt.lease_token,
            output_ref="artifact://again",
        )


def test_fail_records_attempt_error_and_terminal_job(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(task_id=uuid4(), idempotency_key="failure", now=now)
    claimed = repository.claim(worker_id="worker-a", lease_seconds=30, now=now)
    assert claimed is not None
    _, attempt = claimed

    failed = repository.fail(
        job_id=job.job_id,
        lease_token=attempt.lease_token,
        error="provider unavailable",
        now=now + timedelta(seconds=1),
    )

    assert failed.status is JobStatus.failed
    attempts = repository.attempts(job.job_id)
    assert attempts[0].error == "provider unavailable"
    assert attempts[0].outcome.value == "failed"


def test_retryable_failure_uses_backoff_then_succeeds(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    now = utc_now()
    job = repository.enqueue(
        task_id=uuid4(),
        idempotency_key="transient",
        retry_policy=RetryPolicy(
            max_attempts=2,
            backoff_seconds=5,
            max_backoff_seconds=20,
            retryable_outcomes=frozenset({"transient"}),
        ),
        now=now,
    )
    first = repository.claim(worker_id="worker-a", lease_seconds=30, now=now)
    assert first is not None
    _, first_attempt = first

    queued = repository.record_failure(
        job_id=job.job_id,
        lease_token=first_attempt.lease_token,
        error="temporary outage",
        error_code="transient",
        now=now + timedelta(seconds=1),
    )
    assert queued.status is JobStatus.queued
    assert repository.claim(
        worker_id="too-early", lease_seconds=30, now=now + timedelta(seconds=5)
    ) is None
    second = repository.claim(
        worker_id="worker-b", lease_seconds=30, now=now + timedelta(seconds=6)
    )
    assert second is not None
    _, second_attempt = second
    completed = repository.complete(
        job_id=job.job_id,
        lease_token=second_attempt.lease_token,
        output_ref="job-result:success",
        result={"status": "complete"},
        now=now + timedelta(seconds=7),
    )
    assert completed.status is JobStatus.completed
    attempts = repository.attempts(job.job_id)
    assert attempts[0].failure_kind == "execution"
    assert attempts[0].error_code == "transient"


def test_cancel_closes_running_job_and_prevents_claim(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    job = repository.enqueue(task_id=uuid4(), idempotency_key="cancel")
    claimed = repository.claim(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    cancelled = repository.cancel(job_id=job.job_id)
    assert cancelled.status is JobStatus.cancelled
    assert cancelled.cancelled_at is not None
    assert repository.claim(worker_id="worker-b", lease_seconds=30) is None


def test_confidence_failure_is_terminal_and_distinct_from_execution_retry(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    job = repository.enqueue(task_id=uuid4(), idempotency_key="confidence")
    claimed = repository.claim(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    failed = repository.record_failure(
        job_id=job.job_id,
        lease_token=claimed[1].lease_token,
        error="confidence below policy threshold",
        error_code="confidence_threshold",
        failure_kind="confidence",
        retryable=False,
    )

    assert failed.status is JobStatus.failed
    attempt = repository.attempts(job.job_id)[0]
    assert attempt.failure_kind == "confidence"
    assert attempt.error_code == "confidence_threshold"


def test_postgres_dsn_fails_instead_of_silently_using_sqlite() -> None:
    with pytest.raises(ValueError, match="PostgreSQL job storage is not implemented"):
        SqliteJobRepository("postgresql://db.example/galaxz")
