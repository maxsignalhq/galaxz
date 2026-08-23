from pydantic import BaseModel, ConfigDict, Field, field_validator


class AndromedaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: str
    required_skills: list[str]
    priority: str
    payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    timeout_ms: int = Field(ge=0)

    matched_agents: list[str] = Field(default_factory=list)
    assigned_agent: str | None = None
    assignment_reason: str = ""

    result: dict | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_breakdown: dict | None = None
    gaps: list[str] = Field(default_factory=list)
    status: str

    retry_count: int = Field(default=0, ge=0)
    failure_reason: str | None = None
    escalated_to_human: bool = False

    issued_at: str
    completed_at: str | None = None

    @field_validator("task_id", "task_type", "priority", "status", "issued_at")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    def __getitem__(self, key: str):
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)
