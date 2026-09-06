"""Failure-drill runner with auditable, isolated scenario results."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class DrillResult:
    name: str
    outcome: str
    duration_ms: int
    error: str | None = None
    recorded_at: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def run_drill_suite(scenarios: dict[str, Callable[[], None]]) -> list[DrillResult]:
    results = []
    for name, action in scenarios.items():
        started = time.monotonic()
        try:
            action()
            outcome, error = "passed", None
        except Exception as exc:
            outcome, error = "failed", str(exc)
        results.append(DrillResult(name, outcome, int((time.monotonic() - started) * 1000), error, datetime.now(timezone.utc).isoformat()))
    return results
