import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from core.scorecards import ScorecardSigner, generate_private_key_pem, verify_envelope
from orion.storage.event_log import EventLog

AUTH = {"Authorization": "Bearer test-key"}


def _events_db(tmp_path):
    path = str(tmp_path / "events.db")
    asyncio.run(EventLog().init_db(path))
    with sqlite3.connect(path) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO events (id, task_id, skill_id, agent_id, domain, outcome, confidence, "
                "human_verified, latency_ms, created_at, quarantined) "
                "VALUES (?, ?, 'rigel.skill.code_generation', 'rigel', 'code', 'success', 0.9, 0, 120, "
                "datetime('now'), 0)",
                (f"e{i}", f"t{i}"),
            )
    return path


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None
    monkeypatch.setattr(svc, "_andromeda", SimpleNamespace())
    db_path = _events_db(tmp_path)
    monkeypatch.setattr(svc, "_orion_db_path", lambda: db_path)

    def make(signer):
        monkeypatch.setattr(svc, "_scorecard_signer", lambda: signer)
        return TestClient(svc.app)

    return make


@pytest.fixture
def signer():
    return ScorecardSigner.from_pem(generate_private_key_pem())


def test_all_scorecard_routes_require_the_api_key(make_client, signer):
    client = make_client(signer)
    for path in ("/scorecards", "/scorecards/key", "/scorecards/rigel.skill.code_generation"):
        assert client.get(path).status_code == 401


def test_unconfigured_signing_is_503_everywhere(make_client):
    client = make_client(None)
    for path in ("/scorecards", "/scorecards/key", "/scorecards/rigel.skill.code_generation"):
        r = client.get(path, headers=AUTH)
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]


def test_public_key_endpoint(make_client, signer):
    r = make_client(signer).get("/scorecards/key", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == signer.public_key_info()


def test_scorecards_verify_with_the_published_key(make_client, signer):
    client = make_client(signer)
    key = client.get("/scorecards/key", headers=AUTH).json()["public_key"]
    body = client.get("/scorecards", headers=AUTH).json()
    [envelope] = body["scorecards"]
    card = verify_envelope(envelope, key)
    assert card["subject"] == {"agent_id": "rigel", "skill_id": "rigel.skill.code_generation"}
    assert card["metrics"]["tasks"] == 3
    assert card["sample"]["sufficient"] is False
    assert card["issuer"] == "galaxz"


def test_issuer_comes_from_the_environment(make_client, signer, monkeypatch):
    monkeypatch.setenv("GALAXZ_SCORECARD_ISSUER", "acme-labs")
    [envelope] = make_client(signer).get("/scorecards", headers=AUTH).json()["scorecards"]
    assert envelope["scorecard"]["issuer"] == "acme-labs"


def test_skill_endpoint_and_unknown_skill(make_client, signer):
    client = make_client(signer)
    r = client.get("/scorecards/rigel.skill.code_generation", headers=AUTH)
    assert r.status_code == 200 and len(r.json()["scorecards"]) == 1
    assert client.get("/scorecards/nope.skill", headers=AUTH).status_code == 404


@pytest.mark.parametrize("days", [0, 366, -1, "x"])
def test_days_is_validated(make_client, signer, days):
    assert make_client(signer).get("/scorecards", params={"days": days}, headers=AUTH).status_code == 422


def test_empty_orion_database_gives_an_empty_list(make_client, signer, monkeypatch, tmp_path):
    client = make_client(signer)
    monkeypatch.setattr(svc, "_orion_db_path", lambda: str(tmp_path / "missing.db"))
    assert client.get("/scorecards", headers=AUTH).json() == {"scorecards": []}
