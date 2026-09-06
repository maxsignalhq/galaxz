"""Permission-aware usage and outcome reporting for pilot analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GoalReport:
    goal_id: str
    organization_id: str
    repository_id: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    elapsed_ms: int
    outcome: str
    material_edits: int = 0
    failure_class: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def build_usage_report(
    goals: list[GoalReport],
    *,
    organization_id: str,
    repository_id: str,
    can_read: bool,
) -> dict:
    """Return an aggregate report only when org/repository access is granted."""
    if not can_read:
        raise PermissionError("organization and repository access required")
    visible = [g for g in goals if g.organization_id == organization_id and g.repository_id == repository_id]
    return {
        "organization_id": organization_id,
        "repository_id": repository_id,
        "goal_count": len(visible),
        "total_input_tokens": sum(g.input_tokens for g in visible),
        "total_output_tokens": sum(g.output_tokens for g in visible),
        "estimated_cost": round(sum(g.estimated_cost for g in visible), 8),
        "elapsed_ms": sum(g.elapsed_ms for g in visible),
        "outcomes": {outcome: sum(g.outcome == outcome for g in visible) for outcome in ("accepted", "rejected", "edited")},
        "failures": {kind: sum(g.failure_class == kind for g in visible) for kind in ("agent", "infrastructure")},
        "goals": [g.as_dict() for g in visible],
    }


def export_usage_report(report: dict) -> str:
    """Export a stable, JSON-compatible report without secrets or prompt content."""
    import json

    return json.dumps(report, sort_keys=True, separators=(",", ":"))
