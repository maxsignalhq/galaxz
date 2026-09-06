"""Guided first-run setup validation with safe remediation messages."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SetupCheck:
    name: str
    status: str
    remediation: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def setup_readiness(environment: dict[str, str] | None = None) -> dict:
    env = environment or os.environ
    required = {
        "database": ("GALAXZ_DATABASE_URL", "Set GALAXZ_DATABASE_URL to a migrated database."),
        "queue": ("REDIS_URL", "Set REDIS_URL to the Aether Redis service."),
        "object_storage": ("GALAXZ_ARTIFACT_STORAGE", "Set GALAXZ_ARTIFACT_STORAGE to inline, local, or s3."),
        "model": ("ANTHROPIC_MODEL", "Set the provider model name."),
        "identity": ("GALAXZ_API_KEY", "Set an API key or configure explicit local development mode."),
        "github": ("GALAXZ_GITHUB_APP_ID", "Configure a least-privilege GitHub App."),
        "sample_repository": ("GALAXZ_SAMPLE_REPOSITORY", "Set GALAXZ_SAMPLE_REPOSITORY to a readable example repository path."),
    }
    checks = [SetupCheck(name, "ok" if env.get(variable) else "blocked", "configured" if env.get(variable) else remediation) for name, (variable, remediation) in required.items()]
    return {"status": "ready" if all(check.status == "ok" for check in checks) else "blocked", "checks": [check.as_dict() for check in checks]}
