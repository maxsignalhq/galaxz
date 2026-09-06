from core.platform import enterprise_identity, load_test_result, retention_action, sprint_plan, tenant_scope

def test_load_and_tenant_scope_are_isolated():
    assert load_test_result(tenants=2, requests=10, errors=0)["passed"]
    assert tenant_scope(organization_id="o", repository_id="r", resource_scope=("o", "r"))
    assert not tenant_scope(organization_id="o", repository_id="r", resource_scope=("x", "r"))

def test_enterprise_retention_and_sprint_contracts():
    assert enterprise_identity(sso=True, provisioning=True, audit=True)["status"] == "ready"
    assert retention_action(exported=True, deleted=True, within_policy=True)["status"] == "complete"
    assert sprint_plan(5, ("migration",))["sprint"] == 5
