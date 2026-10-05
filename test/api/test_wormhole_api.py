from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


class FakeWormhole:
    def status(self):
        return {
            "configured": True,
            "agents": [{"name": "t", "ok": True, "error": None, "skills": [], "allowed_origins": None}],
        }


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None

    def make(**attrs):
        monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(**attrs))
        return TestClient(svc.app)

    return make


def test_requires_auth(make_client):
    assert make_client().get("/wormhole").status_code == 401


def test_unconfigured_reports_empty(make_client):
    r = make_client().get("/wormhole", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"configured": False, "agents": []}


def test_configured_returns_agent_status(make_client):
    r = make_client(wormhole=FakeWormhole()).get("/wormhole", headers=AUTH)
    assert r.json()["agents"][0]["name"] == "t"
