"""Design-partner pilot lifecycle and evidence capture."""
from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Pilot:
    organization_id: str
    repository_id: str
    participant: str
    workflow: str
    status: str = "planned"

    def advance(self, status: str) -> "Pilot":
        if status not in {"planned", "active", "completed", "paused"}:
            raise ValueError("unsupported pilot status")
        return Pilot(**{**asdict(self), "status": status})
