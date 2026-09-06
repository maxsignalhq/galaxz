import json

import pytest

from core.evaluation.reporting import GoalReport, build_usage_report, export_usage_report


def test_report_aggregates_usage_feedback_and_failure_classes():
    goals = [
        GoalReport("g1", "org", "repo", "model-a", 10, 5, 0.02, 100, "accepted"),
        GoalReport("g2", "org", "repo", "model-a", 4, 2, 0.01, 80, "edited", 2, "agent"),
        GoalReport("other", "other", "repo", "model-b", 99, 99, 1, 999, "rejected", failure_class="infrastructure"),
    ]
    report = build_usage_report(goals, organization_id="org", repository_id="repo", can_read=True)
    assert report["goal_count"] == 2
    assert report["total_input_tokens"] == 14
    assert report["estimated_cost"] == 0.03
    assert report["outcomes"] == {"accepted": 1, "rejected": 0, "edited": 1}
    assert report["failures"] == {"agent": 1, "infrastructure": 0}


def test_report_requires_permission_and_exports_stably():
    with pytest.raises(PermissionError):
        build_usage_report([], organization_id="org", repository_id="repo", can_read=False)
    report = build_usage_report([], organization_id="org", repository_id="repo", can_read=True)
    assert json.loads(export_usage_report(report))["goal_count"] == 0
