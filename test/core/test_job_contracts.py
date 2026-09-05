from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.contracts import AttemptOutcome
from core.contracts import ExecutionAttempt
from core.contracts import Job
from core.contracts import JobStatus
from core.contracts import RetryPolicy
from core.contracts import TaskContract
from core.contracts import validate_job_transition
from core.contracts.contracts import utc_now


def test_job_contract_is_versioned_immutable_and_round_trips() -> None:
    job = Job(task_id=uuid4(), idempotency_key="request-123", priority=10)

    assert job.contract_version == "1.0"
    assert Job.model_validate_json(job.model_dump_json()) == job
    with pytest.raises(ValidationError):
        job.status = JobStatus.running


def test_attempt_requires_consistent_lease_and_terminal_fields() -> None:
    started_at = utc_now()
    attempt = ExecutionAttempt(
        job_id=uuid4(),
        attempt_number=1,
        worker_id="worker-a",
        input_ref="task:123",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(seconds=30),
    )

    assert attempt.outcome is None
    with pytest.raises(ValidationError, match="ended_at and outcome"):
        ExecutionAttempt(
            job_id=uuid4(),
            attempt_number=1,
            worker_id="worker-a",
            input_ref="task:123",
            started_at=started_at,
            lease_expires_at=started_at + timedelta(seconds=30),
            outcome=AttemptOutcome.completed,
        )


def test_completed_attempt_can_reference_output() -> None:
    started_at = utc_now()
    ended_at = started_at + timedelta(seconds=2)
    attempt = ExecutionAttempt(
        job_id=uuid4(),
        attempt_number=1,
        worker_id="worker-a",
        input_ref="task:123",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(seconds=30),
        ended_at=ended_at,
        outcome=AttemptOutcome.completed,
        output_ref="artifact://result/123",
    )

    assert attempt.output_ref == "artifact://result/123"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.queued, JobStatus.running),
        (JobStatus.running, JobStatus.queued),
        (JobStatus.running, JobStatus.completed),
        (JobStatus.running, JobStatus.failed),
        (JobStatus.queued, JobStatus.cancelled),
    ],
)
def test_valid_job_transitions(current: JobStatus, target: JobStatus) -> None:
    validate_job_transition(current, target)


@pytest.mark.parametrize("terminal", list(JobStatus)[2:])
def test_terminal_jobs_reject_all_transitions(terminal: JobStatus) -> None:
    for target in JobStatus:
        with pytest.raises(ValueError, match="invalid job transition"):
            validate_job_transition(terminal, target)


def test_retry_policy_rejects_inverted_backoff() -> None:
    with pytest.raises(ValidationError, match="max_backoff_seconds"):
        RetryPolicy(backoff_seconds=10, max_backoff_seconds=5)


def test_task_contract_remains_the_agent_facing_boundary() -> None:
    task = TaskContract(
        origin="api",
        skill="rigel.skill.code_generation",
        payload={"spec": "hello"},
        confidence_threshold=0.65,
    )

    job = Job(task_id=task.task_id, idempotency_key="request-123")
    assert job.task_id == task.task_id
