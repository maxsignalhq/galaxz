from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from .contracts import utc_now


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AttemptOutcome(str, Enum):
    completed = "completed"
    failed = "failed"
    lease_expired = "lease_expired"
    cancelled = "cancelled"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=3, ge=1)
    backoff_seconds: float = Field(default=1.0, ge=0.0)
    max_backoff_seconds: float = Field(default=60.0, ge=0.0)
    retryable_outcomes: tuple[str, ...] = ("timeout", "transient", "worker_lost")

    @model_validator(mode="after")
    def validate_backoff(self) -> "RetryPolicy":
        if self.max_backoff_seconds < self.backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least backoff_seconds")
        return self


class Job(BaseModel):
    """Versioned durable-execution record; separate from agent-facing TaskContract."""

    model_config = ConfigDict(frozen=True)

    contract_version: Literal["1.0"] = "1.0"
    job_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    status: JobStatus = JobStatus.queued
    priority: int = Field(default=0, ge=-100, le=100)
    idempotency_key: str
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    available_at: datetime = Field(default_factory=utc_now)
    cancellation_requested_at: datetime | None = None
    cancelled_at: datetime | None = None

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be empty")
        return value

    @field_validator(
        "created_at",
        "updated_at",
        "available_at",
        "cancellation_requested_at",
        "cancelled_at",
    )
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_cancellation(self) -> "Job":
        if self.cancelled_at is not None and self.status is not JobStatus.cancelled:
            raise ValueError("cancelled_at requires cancelled status")
        if self.status is JobStatus.cancelled and self.cancelled_at is None:
            raise ValueError("cancelled status requires cancelled_at")
        return self


class ExecutionAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["1.0"] = "1.0"
    attempt_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    attempt_number: int = Field(ge=1)
    worker_id: str
    input_ref: str
    lease_token: UUID = Field(default_factory=uuid4)
    lease_expires_at: datetime
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    outcome: AttemptOutcome | None = None
    failure_kind: Literal["execution", "confidence"] | None = None
    error_code: str | None = None
    error: str | None = None
    output_ref: str | None = None

    @field_validator("worker_id", "input_ref")
    @classmethod
    def validate_worker_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("worker_id must not be empty")
        return value

    @field_validator("lease_expires_at", "started_at", "ended_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_terminal_fields(self) -> "ExecutionAttempt":
        if (self.ended_at is None) != (self.outcome is None):
            raise ValueError("ended_at and outcome must be set together")
        if self.error is not None and self.outcome is not AttemptOutcome.failed:
            raise ValueError("error requires failed outcome")
        if (self.failure_kind is not None or self.error_code is not None) and self.outcome is not AttemptOutcome.failed:
            raise ValueError("failure metadata requires failed outcome")
        if self.output_ref is not None and self.outcome is not AttemptOutcome.completed:
            raise ValueError("output_ref requires completed outcome")
        if self.lease_expires_at <= self.started_at:
            raise ValueError("lease_expires_at must be after started_at")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        return self


_VALID_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.queued: frozenset({JobStatus.running, JobStatus.cancelled}),
    JobStatus.running: frozenset(
        {
            JobStatus.queued,
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
        }
    ),
    JobStatus.completed: frozenset(),
    JobStatus.failed: frozenset(),
    JobStatus.cancelled: frozenset(),
}


def validate_job_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in _VALID_JOB_TRANSITIONS[current]:
        raise ValueError(f"invalid job transition: {current.value} -> {target.value}")
