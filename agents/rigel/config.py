from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RigelConfig(BaseSettings):
    execution_calibration_enabled: bool = True
    execution_timeout_s: int = Field(default=30, ge=1)
    execution_image: str = "galaxz:latest"
    redis_url: str = Field(
        default="redis://aether:6379",
        validation_alias=AliasChoices("RIGEL_REDIS_URL", "REDIS_URL"),
    )
    confidence_completion_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    confidence_failure_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    confidence_parse_error_fallback: float = Field(default=0.75, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(
        env_prefix="RIGEL_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )
