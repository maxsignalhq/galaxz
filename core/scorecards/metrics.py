"""Compute per-(agent, skill) scorecards from Orion's events table."""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone

SCORECARD_VERSION = "1.0"
MIN_TASKS = 20
_Z95 = 1.96


def wilson_interval(successes: int, n: int, z: float = _Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)


def _percentile(sorted_values: list[float], q: int) -> int | None:
    if not sorted_values:
        return None
    rank = max(1, math.ceil(q / 100 * len(sorted_values)))
    return int(sorted_values[rank - 1])


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scorecard(
    agent_id: str, skill_id: str, rows: list[tuple], *, issuer: str, days: int, now: datetime, organization_id: str | None = None
) -> dict:
    tasks = len(rows)
    outcomes = [r[0] for r in rows]
    successes = outcomes.count("success")
    latencies = sorted(r[3] for r in rows if r[3] is not None)
    low, high = wilson_interval(successes, tasks)
    return {
        "version": SCORECARD_VERSION,
        "issuer": issuer,
        # Only other organizations are named, so platform-wide (`default`) cards stay byte-identical.
        "subject": {"agent_id": agent_id, "skill_id": skill_id, **({"organization_id": organization_id} if organization_id not in (None, "default") else {})},
        "issued_at": _iso(now),
        "window": {"from": _iso(now - timedelta(days=days)), "to": _iso(now), "days": days},
        "metrics": {
            "tasks": tasks,
            "success_rate": round(successes / tasks, 4),
            "success_rate_ci95": [round(low, 4), round(high, 4)],
            "partial_rate": round(outcomes.count("partial") / tasks, 4),
            "fail_rate": round(outcomes.count("fail") / tasks, 4),
            "avg_confidence": round(sum(r[1] for r in rows) / tasks, 4),
            "human_verified_rate": round(sum(1 for r in rows if r[2]) / tasks, 4),
            "latency_ms_p50": _percentile(latencies, 50),
            "latency_ms_p95": _percentile(latencies, 95),
        },
        "sample": {"min_tasks": MIN_TASKS, "sufficient": tasks >= MIN_TASKS},
    }


def build_scorecards(
    db_path: str,
    *,
    days: int = 30,
    issuer: str = "galaxz",
    skill_id: str | None = None,
    now: datetime | None = None,
    organization_id: str | None,
) -> list[dict]:
    """Scorecards over one organization's events (``None`` = every organization, platform internals only)."""
    if not os.path.exists(db_path):
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    query = (
        "SELECT agent_id, skill_id, outcome, confidence, human_verified, latency_ms FROM events "
        "WHERE quarantined = 0 AND created_at >= ? AND (? IS NULL OR organization_id = ?)"
    )
    params: list = [cutoff, organization_id, organization_id]
    if skill_id is not None:
        query += " AND skill_id = ?"
        params.append(skill_id)
    try:
        with sqlite3.connect(db_path) as conn:
            fetched = conn.execute(query, params).fetchall()
    except sqlite3.Error:
        return []
    groups: dict[tuple[str, str], list[tuple]] = {}
    for agent_id, skill, outcome, confidence, verified, latency in fetched:
        groups.setdefault((skill, agent_id), []).append((outcome, confidence or 0.0, verified, latency))
    return [
        _scorecard(agent, skill, rows, issuer=issuer, days=days, now=now, organization_id=organization_id)
        for (skill, agent), rows in sorted(groups.items())
    ]
