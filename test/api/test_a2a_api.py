from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from core.a2a.config import A2AConfig, CallerConfig
from core.contracts import SkillDefinition, SkillManifest
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry

SKILL = "rigel.skill.code_generation"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None  # rebuild so ApiKeyMiddleware re-reads the key
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[SkillDefinition(skill_id=SKILL, description="code", input_schema={}, output_schema={})],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(registry=registry))
    monkeypatch.setattr(svc, "_jobs", lambda: jobs)
    monkeypatch.setattr(svc, "_a2a_config", lambda: A2AConfig(callers=(CallerConfig("tok-a", "a2a:alpha"),)))
    return TestClient(svc.app)


def _rpc(client, headers):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "m1",
                "role": "ROLE_USER",
                "parts": [{"data": {"skill": SKILL, "payload": {"spec": "x"}}}],
            }
        },
    }
    return client.post("/a2a", json=body, headers=headers)


def test_agent_card_is_public_even_with_api_key_set(client):
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["skills"]] == [SKILL]


def test_a2a_uses_its_own_token_not_the_api_key(client):
    api_key_only = _rpc(client, {"Authorization": "Bearer test-key", "A2A-Version": "1.0"})
    assert api_key_only.status_code == 401
    assert api_key_only.headers["WWW-Authenticate"] == "Bearer"  # from the A2A handler, not the middleware

    ok = _rpc(client, {"Authorization": "Bearer tok-a", "A2A-Version": "1.0"})
    assert ok.status_code == 200
    assert ok.json()["result"]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"


def test_other_routes_still_require_the_api_key(client):
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Bearer tok-a"}).status_code == 401
