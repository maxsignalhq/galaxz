from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


class FakeQuasar:
    def status(self):
        return {"configured": True, "servers": [{"name": "fs", "ok": True, "error": None, "tools": [], "allowed_origins": None}]}


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None

    def make(**attrs):
        monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(**attrs))
        return TestClient(svc.app)

    return make


def test_requires_auth(make_client):
    assert make_client().get("/quasar").status_code == 401


def test_unconfigured_reports_empty(make_client):
    r = make_client().get("/quasar", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"configured": False, "servers": []}


def test_configured_returns_agent_status(make_client):
    r = make_client(quasar=FakeQuasar()).get("/quasar", headers=AUTH)
    assert r.json()["servers"][0]["name"] == "fs"
