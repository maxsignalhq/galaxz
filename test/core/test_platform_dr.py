from core.platform import disaster_recovery_objectives

def test_dr_objectives_report_at_risk_when_restore_is_unverified():
    assert disaster_recovery_objectives(backup=True, restore=False, failover=True)["status"] == "at_risk"
