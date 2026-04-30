from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"
    retrying = "retrying"


class VegaStage(str, Enum):
    analyzer = "analyzer"
    test_designer = "test_designer"
    bug_reporter = "bug_reporter"


class VegaStageRecord(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    run_id: str
    agent: str = "vega"
    stage: VegaStage
    status: TaskStatus = TaskStatus.pending
    retry_count: int = 0
    max_retries: int = 3
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    provider: str
    model: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    error_code: str | None = None
    quality_score: float | None = None
    used_in_training: bool = False


VALID_TRANSITIONS: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.pending: [TaskStatus.running],
    TaskStatus.running: [TaskStatus.complete, TaskStatus.retrying, TaskStatus.failed],
    TaskStatus.retrying: [TaskStatus.running, TaskStatus.failed],
    TaskStatus.complete: [],
    TaskStatus.failed: [],
}


def transition_status(record: VegaStageRecord, new_status: TaskStatus) -> VegaStageRecord:
    if new_status not in VALID_TRANSITIONS[record.status]:
        raise ValueError(f"Invalid transition: {record.status} -> {new_status}")

    updates: dict[str, Any] = {"status": new_status}
    if new_status == TaskStatus.running:
        updates["started_at"] = utc_now()
    elif new_status in (TaskStatus.complete, TaskStatus.failed):
        updates["completed_at"] = utc_now()

    return record.model_copy(update=updates)
