from core.observability import evaluate_alerts


def test_alerts_cover_operational_failures_with_grouping():
    alerts = evaluate_alerts({"oldest_queue_age_seconds": 901, "lease_churn": 3, "repeated_failures": 4, "dead_jobs": 1, "database_pressure": 0.95, "object_storage_errors": 2})
    assert {alert.key for alert in alerts} == {"queue.stuck", "worker.lease_churn", "agent.repeated_failure", "jobs.dead", "database.pressure", "object_storage.errors"}
    assert all(alert.group for alert in alerts)


def test_alert_evaluation_is_quiet_when_healthy():
    assert evaluate_alerts({}) == []
