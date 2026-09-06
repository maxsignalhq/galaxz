"""Structured pilot feedback and support escalation records."""
from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class SupportEscalation:
    organization_id: str
    repository_id: str
    summary: str
    severity: str = "normal"
    status: str = "open"

    def close(self) -> "SupportEscalation":
        return SupportEscalation(**{**asdict(self), "status": "closed"})

    def as_public_dict(self) -> dict:
        return asdict(self)
