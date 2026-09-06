from core.setup import setup_readiness


def test_setup_readiness_reports_actionable_blockers_without_values():
    report = setup_readiness({"GALAXZ_API_KEY": "secret-value"})
    assert report["status"] == "blocked"
    assert "secret-value" not in str(report)
    assert any(item["name"] == "database" and item["status"] == "blocked" for item in report["checks"])


def test_setup_readiness_is_ready_when_required_integrations_exist():
    env = {key: "configured" for key in ("GALAXZ_DATABASE_URL", "REDIS_URL", "GALAXZ_ARTIFACT_STORAGE", "ANTHROPIC_MODEL", "GALAXZ_API_KEY", "GALAXZ_GITHUB_APP_ID", "GALAXZ_SAMPLE_REPOSITORY")}
    assert setup_readiness(env)["status"] == "ready"
