"""Bounded-cardinality operational and usage metrics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: float
    labels: tuple[tuple[str, str], ...]


class MetricsRegistry:
    def __init__(self, *, allowed_labels: tuple[str, ...] = ("agent", "model", "skill", "outcome")):
        self.allowed_labels = frozenset(allowed_labels)
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = Lock()

    def observe(self, name: str, value: float = 1, **labels: str) -> None:
        safe = tuple(sorted((key, str(value)) for key, value in labels.items() if key in self.allowed_labels))
        with self._lock:
            self._values[(name, safe)] += value

    def snapshot(self) -> list[MetricSample]:
        with self._lock:
            return [MetricSample(name, value, labels) for (name, labels), value in sorted(self._values.items())]
