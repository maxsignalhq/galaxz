"""Confidence calibration and reliability reporting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationReport:
    sample_count: int
    expected_calibration_error: float | None
    bins: tuple[dict, ...]
    insufficient_samples: bool

    def as_dict(self) -> dict:
        return {"sample_count": self.sample_count, "expected_calibration_error": self.expected_calibration_error, "bins": list(self.bins), "insufficient_samples": self.insufficient_samples}


def calibrate(records: list[dict], *, bins: int = 10, minimum_samples: int = 20) -> CalibrationReport:
    if bins <= 0:
        raise ValueError("bins must be positive")
    groups = [[] for _ in range(bins)]
    for record in records:
        confidence = min(1.0, max(0.0, float(record["confidence"])))
        groups[min(bins - 1, int(confidence * bins))].append((confidence, bool(record["success"])))
    report_bins = []
    weighted_error = 0.0
    for index, group in enumerate(groups):
        if not group:
            continue
        mean_confidence = sum(item[0] for item in group) / len(group)
        accuracy = sum(item[1] for item in group) / len(group)
        weighted_error += abs(mean_confidence - accuracy) * len(group)
        report_bins.append({"lower": index / bins, "upper": (index + 1) / bins, "count": len(group), "confidence": mean_confidence, "accuracy": accuracy})
    enough = len(records) >= minimum_samples
    return CalibrationReport(len(records), weighted_error / len(records) if records and enough else None, tuple(report_bins), not enough)
