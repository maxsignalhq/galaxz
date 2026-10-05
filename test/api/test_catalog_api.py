import pytest
import yaml
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


def _package(root, agent_id="demo", version="0.1.0"):
    folder = root / agent_id / version
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": agent_id,
                "agent_name": "Demo",
                "version": version,
                "skills": [{"skill_id": f"{agent_id}.skill.hi", "description": "d", "steps": [{"user": "u"}]}],
            }
        )
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    catalog, agents = tmp_path / "catalog", tmp_path / "agents"
    catalog.mkdir()
    agents.mkdir()
    _package(catalog)
    _package(catalog, agent_id="rigel")
    monkeypatch.setenv("GALAXZ_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("GALAXZ_AGENTS_DIR", str(agents))
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None
    c = TestClient(svc.app)
    c.agents_dir = agents
    return c


def test_catalog_requires_auth(client):
    assert client.get("/catalog").status_code == 401
    assert client.post("/catalog/demo/install").status_code == 401


def test_list_install_and_conflict(client):
    assert [e["agent_id"] for e in client.get("/catalog", headers=AUTH).json()] == ["demo"]

    r = client.post("/catalog/demo/install", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "installed" and r.json()["restart_required"] is True
    assert (client.agents_dir / "demo.yaml").exists()
    assert client.get("/catalog", headers=AUTH).json()[0]["installed_version"] == "0.1.0"

    assert client.post("/catalog/demo/install", headers=AUTH).json()["status"] == "unchanged"
    (client.agents_dir / "demo.yaml").write_text("agent_id: demo\n")
    assert client.post("/catalog/demo/install", headers=AUTH).status_code == 409
    forced = client.post("/catalog/demo/install", headers=AUTH, json={"force": True})
    assert forced.status_code == 200 and forced.json()["status"] == "installed"


def test_not_found_and_reserved(client):
    assert client.post("/catalog/ghost/install", headers=AUTH).status_code == 404
    assert client.post("/catalog/demo/install", headers=AUTH, json={"version": "9.9.9"}).status_code == 404
    assert client.post("/catalog/rigel/install", headers=AUTH).status_code == 422
    assert client.post("/catalog/demo/install", headers=AUTH, json={"version": "bad"}).status_code == 422
