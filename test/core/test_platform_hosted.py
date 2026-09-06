from core.platform import hosted_readiness

def test_hosted_readiness_requires_billing_and_recovery_evidence():
    assert hosted_readiness(billing=True, backups=True, restore_test=False, monitoring=True)["status"] == "blocked"
