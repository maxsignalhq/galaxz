import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as andromeda_service
from agents.andromeda.middleware.auth import _EXEMPT_ROUTES
from core.accounts import declared_permission, get_account_store
from core.security.audit import default_audit_log
from test.api.test_andromeda_api import FakeAether, FakeAndromeda


def _client(monkeypatch, *, api_key=None):
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")
    if api_key:
        monkeypatch.setenv("GALAXZ_API_KEY", api_key)
    else:
        monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
    andromeda_service.app.middleware_stack = None
    monkeypatch.setattr(andromeda_service, "boot", lambda: FakeAndromeda())
    monkeypatch.setattr(andromeda_service, "get_aether_client", lambda: FakeAether())
    return TestClient(andromeda_service.app, raise_server_exceptions=False)


def _token(email, role, *, token_role=None):
    store = get_account_store()
    store.create_user(email, role)
    return {"Authorization": "Bearer " + store.create_token(email, role=token_role)[0]}


TASK = {"task": "Generate an input validator", "skill_id": "code_generation"}


def test_every_non_exempt_route_declares_its_permission():
    exempt = {(method, path) for method, path in _EXEMPT_ROUTES}
    missing = []
    for route in andromeda_service.app.routes:
        for method in getattr(route, "methods", None) or ():
            if method in ("HEAD", "OPTIONS"):
                continue
            if (method, route.path) in exempt:
                continue
            probe = route.path.replace("{", "").replace("}", "")  # path params -> plain segment
            if declared_permission(method, probe) is None:
                missing.append((method, route.path))
    assert missing == [], f"routes without a declared permission (default: admin): {missing}"


def test_open_mode_is_unchanged_when_no_key_and_no_users(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.post("/task", json=TASK).status_code == 200
        me = client.get("/auth/me").json()
    assert me["id"] == "anonymous" and me["role"] == "admin"


def test_legacy_api_key_is_an_admin_in_the_default_organization(monkeypatch):
    with _client(monkeypatch, api_key="legacy") as client:
        headers = {"Authorization": "Bearer legacy"}
        me = client.get("/auth/me", headers=headers).json()
        assert (me["id"], me["kind"], me["role"], me["organization_id"]) == ("api-key", "api-key", "admin", "default")
        assert client.post("/task", json=TASK, headers=headers).status_code == 200
        assert client.get("/audit/verify", headers=headers).status_code == 200


def test_creating_the_first_user_turns_authentication_on(monkeypatch):
    get_account_store().create_user("first@x.io", "admin")
    with _client(monkeypatch) as client:
        assert client.post("/task", json=TASK).status_code == 401
        assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "role,allowed,denied",
    [
        ("viewer", [("GET", "/goals")], [("POST", "/task"), ("POST", "/review/queue/t1/approve"), ("GET", "/audit/verify")]),
        ("operator", [("GET", "/goals"), ("POST", "/task")], [("POST", "/review/queue/t1/approve"), ("POST", "/config"), ("GET", "/audit/events")]),
        ("reviewer", [("GET", "/goals")], [("POST", "/task"), ("POST", "/config")]),
        ("admin", [("GET", "/goals"), ("POST", "/task"), ("GET", "/audit/verify")], []),
    ],
)
def test_role_enforcement(monkeypatch, role, allowed, denied):
    headers = _token(f"{role}@x.io", role)
    with _client(monkeypatch) as client:
        for method, path in allowed:
            response = client.request(method, path, json=TASK if path == "/task" else None, headers=headers)
            assert response.status_code != 403, (role, method, path)
        for method, path in denied:
            response = client.request(method, path, json={}, headers=headers)
            assert response.status_code == 403 and response.json() == {"error": "forbidden"}, (role, method, path)


def test_reviewer_can_reach_a_review_decision(monkeypatch):
    headers = _token("rev@x.io", "reviewer")
    with _client(monkeypatch) as client:
        response = client.post("/review/queue/t1/approve", headers=headers)
    assert response.status_code != 403


def test_undeclared_route_is_admin_only(monkeypatch):
    operator = _token("op@x.io", "operator")
    admin = _token("boss@x.io", "admin")
    with _client(monkeypatch) as client:
        assert client.post("/not-a-real-route", headers=operator).status_code == 403
        assert client.post("/not-a-real-route", headers=admin).status_code == 404


def test_downscoped_token_is_limited_even_for_an_admin_user(monkeypatch):
    headers = _token("boss@x.io", "admin", token_role="viewer")
    with _client(monkeypatch) as client:
        assert client.get("/goals", headers=headers).status_code != 403
        assert client.post("/task", json=TASK, headers=headers).status_code == 403


def test_garbage_and_revoked_tokens_are_401(monkeypatch):
    store = get_account_store()
    store.create_user("a@x.io", "admin")
    token, record = store.create_token("a@x.io")
    store.revoke_token(record["id"])
    with _client(monkeypatch) as client:
        for header in ("Bearer gzt_garbage", f"Bearer {token}", "Basic abc", ""):
            assert client.get("/goals", headers={"Authorization": header}).status_code == 401


def test_exempt_routes_need_no_credentials_even_with_accounts(monkeypatch):
    get_account_store().create_user("a@x.io", "admin")
    with _client(monkeypatch) as client:
        assert client.get("/health").status_code == 200


def test_audit_attributes_actions_to_the_user_and_records_denials(monkeypatch):
    headers = _token("viewer@x.io", "viewer")
    with _client(monkeypatch) as client:
        client.post("/task", json=TASK, headers=headers)
    [event] = [e["event"] for e in default_audit_log().export()]
    assert event["actor"] == "user:viewer@x.io" and event["reason"] == "denied"
    assert event["extra"]["status"] == 403 and event["extra"]["principal_kind"] == "user"


def test_account_store_failure_fails_closed(monkeypatch):
    class Broken:
        def has_users(self):
            raise RuntimeError("db down")

        def authenticate(self, token):
            raise RuntimeError("db down")

    monkeypatch.setattr("agents.andromeda.middleware.auth.get_account_store", lambda: Broken())
    with _client(monkeypatch) as client:
        response = client.post("/task", json=TASK)
    assert response.status_code == 503


class _Candidate:
    status = "pending"


class _CandidateClient:
    def __init__(self):
        self.calls = []

    def get_candidate(self, candidate_id):
        return _Candidate()

    def approve(self, candidate_id, reviewed_by, note):
        self.calls.append(("approve", reviewed_by))

    def reject(self, candidate_id, reviewed_by, note):
        self.calls.append(("reject", reviewed_by))


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_user_decisions_are_attributed_to_the_authenticated_user_not_the_body(monkeypatch, action):
    fake = _CandidateClient()
    headers = _token("rev@x.io", "reviewer")
    with _client(monkeypatch) as client:
        monkeypatch.setattr(andromeda_service, "_candidate_client", fake)  # after lifespan startup sets its own
        response = client.post(
            f"/finetune/candidates/c1/{action}", json={"reviewed_by": "someone-else@evil.io"}, headers=headers
        )
    assert response.status_code == 200
    assert fake.calls == [(action, "user:rev@x.io")]


def test_legacy_api_key_still_uses_the_claimed_name(monkeypatch):
    fake = _CandidateClient()
    with _client(monkeypatch, api_key="legacy") as client:
        monkeypatch.setattr(andromeda_service, "_candidate_client", fake)
        client.post("/finetune/candidates/c1/approve", json={"reviewed_by": "alice"},
                    headers={"Authorization": "Bearer legacy"})
    assert fake.calls == [("approve", "alice")]


def test_lesson_decisions_are_attributed_to_the_authenticated_user(monkeypatch):
    claimed = []

    class Lessons:
        def get(self, candidate_id):
            return object()

        def claim(self, candidate_id, status, reviewed_by, note, edited=None):
            claimed.append((status, reviewed_by))
            return True

    monkeypatch.setattr(andromeda_service, "_lesson_store", lambda: Lessons())
    headers = _token("rev@x.io", "reviewer")
    with _client(monkeypatch) as client:
        response = client.post("/lessons/l1/reject", json={"reviewed_by": "spoof"}, headers=headers)
    assert response.status_code == 200 and claimed == [("rejected", "user:rev@x.io")]
