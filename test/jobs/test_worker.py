from __future__ import annotations

import threading
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from core.contracts import JobStatus
from core.contracts import RetryPolicy
from core.contracts import TaskContract
from core.jobs import CancellationToken
from core.jobs import DurableWorker
from core.jobs import RetryableExecutionError
from core.jobs import SqliteJobRepository
from core.jobs import WorkerConfig


def _task() -> TaskContract:
    return TaskContract(
        origin="test",
        skill="rigel.skill.code_generation",
        payload={"task": "return ok"},
        confidence_threshold=0.65,
    )


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_worker_claims_persisted_task_and_completes(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    task = _task()
    job = repository.enqueue(task_id=task.task_id, task=task, idempotency_key="worker-ok")
    seen: list[TaskContract] = []

    def execute(value: TaskContract, token: CancellationToken) -> dict:
        seen.append(value)
        token.raise_if_cancelled()
        return {"status": "complete"}

    worker = DurableWorker(
        repository,
        execute,
        WorkerConfig(worker_id="worker-1", lease_seconds=1, heartbeat_seconds=0.1),
    )
    assert worker.run_cycle()
    _wait_for(lambda: repository.get_job(job.job_id).status is JobStatus.completed)
    worker.shutdown()

    assert len(seen) == 1
    assert seen[0].model_copy(update={"execution_attempt_id": None}) == task
    assert seen[0].execution_attempt_id == repository.attempts(job.job_id)[0].attempt_id
    assert repository.get_result(job.job_id) == {"status": "complete"}
    assert repository.attempts(job.job_id)[0].worker_id == "worker-1"


def test_worker_retries_classified_failure_then_succeeds(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    task = _task()
    job = repository.enqueue(
        task_id=task.task_id,
        task=task,
        idempotency_key="worker-retry",
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0, max_backoff_seconds=0),
    )
    calls = 0

    def execute(value: TaskContract, token: CancellationToken) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableExecutionError("temporary", error_code="transient")
        return {"attempt": calls}

    worker = DurableWorker(
        repository,
        execute,
        WorkerConfig(worker_id="worker-1", lease_seconds=1, heartbeat_seconds=0.1),
    )
    assert worker.run_cycle()
    _wait_for(lambda: repository.get_job(job.job_id).status is JobStatus.queued)
    _wait_for(worker.run_cycle)
    _wait_for(lambda: repository.get_job(job.job_id).status is JobStatus.completed)
    worker.shutdown()

    assert calls == 2
    assert [attempt.error_code for attempt in repository.attempts(job.job_id)] == [
        "transient",
        None,
    ]


def test_running_cancellation_signals_executor_and_blocks_late_result(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    task = _task()
    job = repository.enqueue(task_id=task.task_id, task=task, idempotency_key="cancel")
    started = threading.Event()

    def execute(value: TaskContract, token: CancellationToken) -> dict:
        started.set()
        assert token.wait(2)
        token.raise_if_cancelled()
        return {"should": "not persist"}

    worker = DurableWorker(
        repository,
        execute,
        WorkerConfig(worker_id="worker-1", lease_seconds=1, heartbeat_seconds=0.05),
    )
    worker.run_cycle()
    assert started.wait(1)
    repository.cancel(job_id=job.job_id)
    _wait_for(lambda: repository.get_job(job.job_id).status is JobStatus.cancelled)
    worker.shutdown()

    assert repository.get_result(job.job_id) is None
    assert repository.attempts(job.job_id)[0].outcome.value == "cancelled"


def test_expired_attempt_is_reclaimed_and_cannot_overwrite_new_result(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    task = _task()
    job = repository.enqueue(
        task_id=task.task_id,
        task=task,
        idempotency_key="reclaim",
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0, max_backoff_seconds=0),
    )
    now = datetime.now(timezone.utc)
    first = repository.claim(worker_id="crashed", lease_seconds=1, now=now)
    assert first is not None
    first_token = first[1].lease_token
    reclaimed = repository.reclaim_expired(now=now + timedelta(seconds=2))
    assert [item.job_id for item in reclaimed] == [job.job_id]

    second = repository.claim(
        worker_id="replacement", lease_seconds=30, now=now + timedelta(seconds=2)
    )
    assert second is not None
    repository.complete(
        job_id=job.job_id,
        lease_token=second[1].lease_token,
        output_ref="replacement-result",
        result={"winner": "replacement"},
        now=now + timedelta(seconds=3),
    )

    from core.jobs import InvalidJobState

    try:
        repository.complete(
            job_id=job.job_id,
            lease_token=first_token,
            output_ref="late-result",
            result={"winner": "crashed"},
            now=now + timedelta(seconds=3),
        )
    except InvalidJobState:
        pass
    else:
        raise AssertionError("late completion must be rejected")
    assert repository.get_result(job.job_id) == {"winner": "replacement"}


def test_stop_request_prevents_new_claims_while_active_attempt_drains(tmp_path) -> None:
    repository = SqliteJobRepository(tmp_path / "jobs.db")
    first_task = _task()
    second_task = _task()
    first_job = repository.enqueue(
        task_id=first_task.task_id,
        task=first_task,
        idempotency_key="drain-first",
    )
    second_job = repository.enqueue(
        task_id=second_task.task_id,
        task=second_task,
        idempotency_key="drain-second",
    )
    started = threading.Event()
    release = threading.Event()

    def execute(value: TaskContract, token: CancellationToken) -> dict:
        started.set()
        assert release.wait(1)
        return {"status": "complete"}

    worker = DurableWorker(
        repository,
        execute,
        WorkerConfig(worker_id="worker-1", lease_seconds=1, heartbeat_seconds=0.1),
    )
    assert worker.run_cycle()
    assert started.wait(1)
    worker.request_stop()
    assert not worker.run_cycle()
    release.set()
    worker.shutdown()

    assert repository.get_job(first_job.job_id).status is JobStatus.completed
    assert repository.get_job(second_job.job_id).status is JobStatus.queued
