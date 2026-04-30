from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskContract(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    origin: str
    skill: str
    payload: dict
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    deadline_ms: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("origin", "skill")
    @classmethod
    def validate_non_empty_str(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class SkillDefinition(BaseModel):
    skill_id: str
    description: str
    input_schema: dict
    output_schema: dict
    avg_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    avg_latency_ms: int = Field(default=1000, ge=0)

    @field_validator("skill_id", "description")
    @classmethod
    def validate_skill_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class SkillManifest(BaseModel):
    agent_id: str
    agent_name: str
    version: str
    skills: list[SkillDefinition]
    health_endpoint: str
    registered_at: datetime = Field(default_factory=utc_now)
    heartbeat_interval_s: int = Field(default=30, ge=1)

    @field_validator("agent_id", "agent_name", "version", "health_endpoint")
    @classmethod
    def validate_manifest_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class RefineryFeedbackEvent(BaseModel):
    task_id: UUID
    agent_id: str
    skill: str
    outcome: Literal["success", "fail", "partial"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    execution_outcome: str | None = None
    human_verified: bool = False
    human_correction: str | None = None
    latency_ms: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("agent_id", "skill")
    @classmethod
    def validate_feedback_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


def validate_feedback_event(
    event: RefineryFeedbackEvent,
    manifest: SkillManifest,
) -> RefineryFeedbackEvent:
    if event.agent_id != manifest.agent_id:
        raise ValueError(
            f"feedback agent_id={event.agent_id} does not match manifest agent_id={manifest.agent_id}"
        )

    valid_skill_ids = {skill.skill_id for skill in manifest.skills}
    if event.skill not in valid_skill_ids:
        raise ValueError(
            f"feedback skill={event.skill} is not registered for agent_id={manifest.agent_id}"
        )

    return event


class OutcomeType(str, Enum):
    completed = "completed"
    failed = "failed"
    escalated = "escalated"
    corrected = "corrected"
    approved = "approved"
    rejected = "rejected"


class FeedbackEvent(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    task_category: str
    agent_id: str
    outcome: OutcomeType
    confidence_score: float = Field(ge=0.0, le=1.0)
    input_hash: str
    agent_output: dict
    human_correction: dict | None = None
    human_verified: bool = False
    latency_ms: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class ExampleSource(str, Enum):
    human_correction = "human_correction"
    high_confidence_success = "high_confidence_success"


class TrainingExample(BaseModel):
    prompt: str
    completion: str
    domain: str
    source: ExampleSource
    quality_score: float = Field(ge=0.0, le=1.0)
    feedback_event_id: UUID
    created_at: datetime
    exported_at: Optional[datetime] = None
