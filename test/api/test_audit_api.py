import sqlite3

from fastapi.testclient import TestClient

import services.andromeda_service as andromeda_service
from core.security.audit import default_audit_log
from test.api.test_andromeda_api import AUTH_HEADERS, FakeAether, FakeAndromeda, _reset_auth


def _client(monkeypatch, *, auth=True):
    if auth:
        _reset_auth(monkeypatch)
    else:
        monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")
        monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
        andromeda_service.app.middleware_stack = None
    monkeypatch.setattr(andromeda_service, "boot", lambda: FakeAndromeda())
    monkeypatch.setattr(andromeda_service, "get_aether_client", lambda: FakeAether())
    return TestClient(andromeda_service.app)


def _events():
    return [item["event"] for item in default_audit_log().export()]


def test_authenticated_mutation_is_recorded_without_body_or_query(monkeypatch):
    with _client(monkeypatch) as client:
        client.post(
            "/task?token=leak-me",
            json={"task": "hush-hush-body", "skill_id": "code_generation"},
            headers=AUTH_HEADERS,
        )
    [event] = _events()
    assert event["action"] == "http.post" and event["reason"] == "allowed"
    assert event["actor"] == "api-key"
    assert event["extra"] == {"path": "/task", "status": 200, "principal_kind": "api-key"}
    stored = str(sqlite3.connect(default_audit_log()._db.execute("PRAGMA database_list").fetchone()[2]).execute(
        "SELECT event_json FROM audit_events").fetchall())
    assert "leak-me" not in stored and "hush-hush-body" not in stored


def test_rejected_request_is_recorded_as_unauthenticated(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.post("/task", json={"task": "x", "skill_id": "code_generation"})
    assert response.status_code == 401
    [event] = _events()
    assert event["actor"] == "unauthenticated" and event["reason"] == "denied"
    assert event["extra"]["status"] == 401 and event["extra"]["path"] == "/task"


def test_rejected_get_is_recorded_but_successful_gets_are_not(monkeypatch):
    with _client(monkeypatch) as client:
        client.get("/health")
        client.get("/audit/events")  # no credentials
    [event] = _events()
    assert event["action"] == "http.get" and event["extra"]["status"] == 401


def test_actor_is_anonymous_when_auth_is_disabled(monkeypatch):
    with _client(monkeypatch, auth=False) as client:
        client.post("/task", json={"task": "x", "skill_id": "code_generation"})
    [event] = _events()
    assert event["actor"] == "anonymous" and event["extra"]["principal_kind"] == "anonymous"


def test_exempt_route_is_attributed_to_exempt_route(monkeypatch):
    with _client(monkeypatch) as client:
        client.post("/github/webhook", content=b"{}")
    [event] = _events()
    assert event["actor"] == "exempt-route"


def test_events_endpoint_pages_and_requires_the_key(monkeypatch):
    with _client(monkeypatch) as client:
        for _ in range(3):
            client.post("/task", json={"task": "x", "skill_id": "code_generation"}, headers=AUTH_HEADERS)
        page = client.get("/audit/events?after=1&limit=2", headers=AUTH_HEADERS).json()
        assert [e["sequence"] for e in page["events"]] == [2, 3]
        assert client.get("/audit/events?limit=5000", headers=AUTH_HEADERS).status_code == 422


def test_verify_endpoint_reports_a_valid_then_a_tampered_chain(monkeypatch):
    with _client(monkeypatch) as client:
        client.post("/task", json={"task": "x", "skill_id": "code_generation"}, headers=AUTH_HEADERS)
        ok = client.get("/audit/verify", headers=AUTH_HEADERS).json()
        assert ok["valid"] is True and ok["events"] >= 1
        db = default_audit_log()._db
        db.execute("UPDATE audit_events SET event_json = replace(event_json, 'allowed', 'altered') WHERE sequence=1")
        bad = client.get("/audit/verify", headers=AUTH_HEADERS).json()
        assert bad["valid"] is False and bad["broken_at"] == 1
