from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from core.nebula.store import NebulaStore

AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None
    monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(nebula=NebulaStore(str(tmp_path / "n.db"))))
    return TestClient(svc.app)


def test_memory_requires_auth(client):
    assert client.get("/memory", params={"namespace": "global"}).status_code == 401


def test_create_recall_delete_round_trip(client):
    created = client.post(
        "/memory",
        headers=AUTH,
        json={"namespace": "global", "content": "Use pytest fixtures", "tags": ["testing"]},
    )
    assert created.status_code == 201
    memory_id = created.json()["memory_id"]

    hits = client.get("/memory", headers=AUTH, params={"namespace": "global", "q": "pytest"}).json()
    assert [h["memory_id"] for h in hits] == [memory_id]

    assert client.delete(f"/memory/{memory_id}", headers=AUTH).status_code == 200
    assert client.get("/memory", headers=AUTH, params={"namespace": "global"}).json() == []
    assert client.delete(f"/memory/{memory_id}", headers=AUTH).status_code == 404


def test_blank_content_rejected(client):
    r = client.post("/memory", headers=AUTH, json={"namespace": "global", "content": "  "})
    assert r.status_code == 422


def test_multiple_namespaces_comma_separated(client):
    client.post("/memory", headers=AUTH, json={"namespace": "a", "content": "from a"})
    client.post("/memory", headers=AUTH, json={"namespace": "b", "content": "from b"})
    hits = client.get("/memory", headers=AUTH, params={"namespace": "a,b"}).json()
    assert {h["content"] for h in hits} == {"from a", "from b"}


def test_namespaces_endpoint(client):
    client.post("/memory", headers=AUTH, json={"namespace": "goal:1", "content": "x"})
    client.post("/memory", headers=AUTH, json={"namespace": "global", "content": "y"})
    client.post("/memory", headers=AUTH, json={"namespace": "global", "content": "z"})
    got = client.get("/memory/namespaces", headers=AUTH).json()
    assert got == [{"namespace": "global", "count": 2}, {"namespace": "goal:1", "count": 1}]
