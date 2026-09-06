from core.support import SupportEscalation

def test_support_escalation_preserves_scope_and_closes():
    issue = SupportEscalation("org", "repo", "workflow blocked", "high")
    assert issue.close().status == "closed"
    assert issue.as_public_dict()["organization_id"] == "org"
