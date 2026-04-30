from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrionConfig(BaseSettings):
    redis_url: str = Field(
        default="redis://aether:6379",
        validation_alias=AliasChoices("ORION_REDIS_URL", "REDIS_URL"),
    )
    db_path: str = "orion/data/events.db"
    dataset_path: str = "orion/data/datasets"
    extraction_interval_hours: int = 1
    heuristic_cycle_interval_hours: int = 6
    window_hours: int = 24
    min_quality_score: float = 0.85

    # Heuristic thresholds
    routing_confidence_delta: float = 0.15
    routing_min_sample_size: int = 50
    drift_confidence_drop: float = 0.20
    fine_tune_correction_count: int = 200
    fine_tune_correction_rate: float = 0.40
    escalation_threshold: float = 0.30
    finetune_trigger_threshold: int = 100

    model_config = SettingsConfigDict(
        env_prefix="ORION_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


DEFAULT_CONFIG = OrionConfig()
