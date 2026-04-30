"""
Tests for fine-tune candidate approval/rejection endpoints.

  GET  /finetune/candidates
  POST /finetune/candidates/{candidate_id}/approve
  POST /finetune/candidates/{candidate_id}/reject
  GET  /health  → includes finetune_pending count
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as andromeda_service
from orion.core.candidate_client import CandidateClient
from orion.core.candidate_store import CandidateStore


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_andromeda():
    class FakeRegistry:
        def health_check(self):
            return {"status": "ok", "skill_count": 0, "agents": []}

        def get_all_skills(self):
            return []

        def list_agents(self):
            return []

    class FakeTaskLog:
        def stats(self):
            return {"total": 0}

    class FakeReviewQueue:
        def get_pending(self):
            return []

    class Fake:
        registry = FakeRegistry()
        task_log = FakeTaskLog()
        review_queue = FakeReviewQueue()
        orion = None

    return Fake()


def _fake_aether():
    m = MagicMock()
    m.redis.ping.return_value = True
    m.close.return_value = None
    return m


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def candidates_db(tmp_path):
    return str(tmp_path / "candidates.db")


@pytest.fixture
def events_db(tmp_path):
    return str(tmp_path / "events.db")


@pytest.fixture
def store(candidates_db):
    return CandidateStore(candidates_db)


@pytest.fixture
def client(monkeypatch, events_db, candidates_db):
    monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
    monkeypatch.setattr(andromeda_service, "boot", lambda: _fake_andromeda())
    monkeypatch.setattr(andromeda_service, "get_aether_client", _fake_aether)
    # Redirect _orion_db_path so lifespan derives the test candidates.db
    monkeypatch.setattr(andromeda_service, "_orion_db_path", lambda: events_db)
    andromeda_service.app.middleware_stack = None
    with TestClient(andromeda_service.app) as c:
        yield c


# ── tests ─────────────────────────────────────────────────────────────────────


def test_list_pending_empty(client):
    r = client.get("/finetune/candidates")
    assert r.status_code == 200
    assert r.json() == {"candidates": []}


def test_list_pending_returns_pending_candidates(client, store):
    store.add("vega", 120, 0.91)
    store.add("rigel", 200, 0.88)

    r = client.get("/finetune/candidates")
    assert r.status_code == 200
    body = r.json()
    ids = {c["agent_id"] for c in body["candidates"]}
    assert ids == {"vega", "rigel"}
    for c in body["candidates"]:
        assert c["status"] == "pending"


def test_approve_sets_status_and_records_reviewer(client, candidates_db, store):
    candidate = store.add("vega", 100, 0.90)
    cid = candidate.candidate_id

    r = client.post(
        f"/finetune/candidates/{cid}/approve",
        json={"reviewed_by": "alice", "reviewer_note": "looks good"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "approved", "candidate_id": cid}

    updated = CandidateClient(candidates_db).get_candidate(cid)
    assert updated.status == "approved"
    assert updated.reviewed_by == "alice"
    assert updated.reviewer_note == "looks good"
    assert updated.reviewed_at is not None


def test_reject_sets_status_and_records_reviewer(client, candidates_db, store):
    candidate = store.add("rigel", 110, 0.87)
    cid = candidate.candidate_id

    r = client.post(
        f"/finetune/candidates/{cid}/reject",
        json={"reviewed_by": "bob"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "rejected", "candidate_id": cid}

    updated = CandidateClient(candidates_db).get_candidate(cid)
    assert updated.status == "rejected"
    assert updated.reviewed_by == "bob"
    assert updated.reviewer_note is None


def test_double_approve_returns_409(client, store):
    candidate = store.add("vega", 100, 0.90)
    cid = candidate.candidate_id

    client.post(f"/finetune/candidates/{cid}/approve", json={"reviewed_by": "alice"})
    r = client.post(f"/finetune/candidates/{cid}/approve", json={"reviewed_by": "alice"})

    assert r.status_code == 409


def test_approve_unknown_candidate_returns_404(client):
    r = client.post(
        "/finetune/candidates/does-not-exist/approve",
        json={"reviewed_by": "alice"},
    )
    assert r.status_code == 404


def test_reject_unknown_candidate_returns_404(client):
    r = client.post(
        "/finetune/candidates/does-not-exist/reject",
        json={"reviewed_by": "bob"},
    )
    assert r.status_code == 404


def test_approved_candidate_not_in_pending_list(client, store):
    c1 = store.add("vega", 100, 0.90)
    c2 = store.add("rigel", 150, 0.86)

    client.post(
        f"/finetune/candidates/{c1.candidate_id}/approve",
        json={"reviewed_by": "alice"},
    )

    r = client.get("/finetune/candidates")
    ids = {c["agent_id"] for c in r.json()["candidates"]}
    assert "vega" not in ids
    assert "rigel" in ids


def test_health_includes_finetune_pending(client, store):
    store.add("vega", 100, 0.90)
    store.add("rigel", 150, 0.86)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["finetune_pending"] == 2
