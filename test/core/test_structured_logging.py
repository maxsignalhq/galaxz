import json
import logging

from core.observability import correlation_context
from core.observability.logging import JsonFormatter


def test_json_logging_contains_correlation_and_redacts_sensitive_fields():
    record = logging.LogRecord("worker", logging.INFO, __file__, 1, "job_started", (), None)
    record.job_id = "job-1"
    record.token = "do-not-log"
    with correlation_context(goal_id="goal-1", attempt_id="attempt-1"):
        payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "job_started"
    assert payload["goal_id"] == "goal-1"
    assert payload["attempt_id"] == "attempt-1"
    assert payload["job_id"] == "job-1"
    assert payload["token"] == "[REDACTED]"
