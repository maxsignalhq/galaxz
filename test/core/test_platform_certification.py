from core.platform import certify_agent

def test_agent_certification_requires_all_checks():
    assert certify_agent(tests=True, security=True, permissions=False)["certified"] is False
