from core.evaluation.release import ReleaseEvidence, evaluate_release


def test_release_gate_approves_complete_evidence():
    assert evaluate_release(ReleaseEvidence(True, True, True, True))["status"] == "approved"


def test_release_gate_blocks_security_or_critical_findings():
    result = evaluate_release(ReleaseEvidence(True, False, True, True, unresolved_critical_findings=1))
    assert result["status"] == "blocked"
    assert result["checks"]["security"] is False
    assert result["checks"]["critical_findings"] is False
