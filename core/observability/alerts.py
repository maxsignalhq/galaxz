"""Actionable, grouped operational alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    key: str
    severity: str
    message: str
    identifiers: dict
    group: str

    def as_dict(self) -> dict:
        return {"key": self.key, "severity": self.severity, "message": self.message, "identifiers": self.identifiers, "group": self.group}


def evaluate_alerts(snapshot: dict, *, queue_age_seconds: int = 900, failure_threshold: int = 3) -> list[Alert]:
    alerts = []
    if snapshot.get("oldest_queue_age_seconds", 0) >= queue_age_seconds:
        alerts.append(Alert("queue.stuck", "warning", "queued work is older than the service target", {"age_seconds": snapshot["oldest_queue_age_seconds"]}, "queue"))
    if snapshot.get("lease_churn", 0) >= failure_threshold:
        alerts.append(Alert("worker.lease_churn", "critical", "workers are repeatedly losing leases", {"count": snapshot["lease_churn"]}, "worker"))
    if snapshot.get("repeated_failures", 0) >= failure_threshold:
        alerts.append(Alert("agent.repeated_failure", "critical", "agent failures exceeded the retry threshold", {"count": snapshot["repeated_failures"]}, "agent"))
    if snapshot.get("dead_jobs", 0):
        alerts.append(Alert("jobs.dead", "critical", "dead jobs require operator review", {"count": snapshot["dead_jobs"]}, "jobs"))
    if snapshot.get("database_pressure", 0) >= 0.9:
        alerts.append(Alert("database.pressure", "critical", "database pressure is above the safe threshold", {"ratio": snapshot["database_pressure"]}, "database"))
    if snapshot.get("object_storage_errors", 0):
        alerts.append(Alert("object_storage.errors", "error", "object storage operations are failing", {"count": snapshot["object_storage_errors"]}, "object-storage"))
    return alerts
