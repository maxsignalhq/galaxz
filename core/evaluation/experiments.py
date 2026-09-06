"""Reproducible experiment metadata and aggregate comparisons."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentSpec:
    dataset: str
    model: str
    prompt_version: str
    agent_version: str
    routing_version: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def compare_experiments(results: list[dict], *, minimum_samples: int = 20) -> dict:
    if not results:
        return {"sample_count": 0, "insufficient_samples": True, "metrics": {}}
    count = len(results)
    metrics = {}
    for key in ("quality", "latency_ms", "cost_usd", "escalated"):
        values = [float(item[key]) for item in results if key in item]
        if not values:
            continue
        mean = sum(values) / len(values)
        metrics[key] = {"mean": mean, "sample_count": len(values), "standard_error": (math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / math.sqrt(len(values))) if len(values) > 1 else None}
    return {"sample_count": count, "insufficient_samples": count < minimum_samples, "metrics": metrics}
