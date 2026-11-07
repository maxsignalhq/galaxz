import pytest

from core.accounts.permissions import ROLES, allows, declared_permission, required_permission


@pytest.mark.parametrize(
    "method,path,permission",
    [
        ("GET", "/goals", "read"),
        ("GET", "/goals/123", "read"),
        ("POST", "/goals", "work:write"),
        ("POST", "/goals/123/cancel", "work:write"),
        ("POST", "/goals/123/tasks/456/rerun", "work:write"),
        ("DELETE", "/memory/9", "work:write"),
        ("POST", "/review/queue/abc/approve", "review:decide"),
        ("POST", "/review/queue/abc/reject", "review:decide"),
        ("POST", "/finetune/candidates/c1/approve", "review:decide"),
        ("POST", "/lessons/c1/reject", "review:decide"),
        ("POST", "/tasks/t1/feedback", "review:decide"),
        ("POST", "/config", "admin"),
        ("GET", "/config", "admin"),
        ("POST", "/repositories", "admin"),
        ("POST", "/catalog/some-agent/install", "admin"),
        ("GET", "/audit/events", "audit:read"),
        ("GET", "/audit/verify", "audit:read"),
        ("GET", "/orion/export", "admin"),
        ("GET", "/auth/me", "read"),
    ],
)
def test_declared_permissions(method, path, permission):
    assert declared_permission(method, path) == permission


def test_undeclared_route_requires_admin():
    assert declared_permission("POST", "/something/new") is None
    assert required_permission("POST", "/something/new") == "admin"
    assert required_permission("GET", "/something/new") == "admin"


def test_method_matters():
    assert declared_permission("DELETE", "/goals") is None
    assert declared_permission("GET", "/task") is None  # only POST /task is declared


def test_role_matrix():
    assert allows("viewer", "read") and not allows("viewer", "work:write")
    assert allows("operator", "work:write") and allows("operator", "read")
    assert not allows("operator", "review:decide")
    assert allows("reviewer", "review:decide") and allows("reviewer", "read")
    assert not allows("reviewer", "work:write")
    for permission in ("read", "work:write", "review:decide", "audit:read", "admin"):
        assert allows("admin", permission)
    assert not allows("operator", "audit:read") and not allows("reviewer", "admin")


def test_unknown_role_has_no_permissions():
    assert not allows("root", "read") and not allows("", "read")
    assert set(ROLES) == {"viewer", "operator", "reviewer", "admin"}
