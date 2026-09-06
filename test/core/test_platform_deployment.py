from core.platform import deployment_plan

def test_deployment_requires_tls_health_and_rollback():
    assert deployment_plan(tls=True, health_checks=True, rollback_version=None)["status"] == "blocked"
