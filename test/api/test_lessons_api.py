import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import NebulaStore
from core.pulsar.registry import PulsarRegistry
from orion.storage.event_log import EventLog

AUTH = {"Authorization": "Bearer test-key"}
SKILL = "rigel.skill.code_generation"
REVIEWER = {"reviewed_by": "alice"}


class CapturingAgent:
    def __init__(self):
        self.contexts = []

    def run(self, skill_id, payload, context):
        self.contexts.append(context)
        return {"result": {"ok": True}, "confidence": 0.95}


def _events_db(tmp_path, count=3):
    path = str(tmp_path / "orion" / "events.db")
    (tmp_path / "orion").mkdir()
    asyncio.run(EventLog().init_db(path))
    with sqlite3.connect(path) as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO events (id, task_id, skill_id, agent_id, domain, outcome, confidence, human_verified, "
                "payload, result, human_correction, latency_ms, created_at, quarantined) "
                "VALUES (?,?,?,?,'code','success',0.9,1,'{}','{}',?,100,?,0)",
                (f"e{i}", f"t{i}", SKILL, "rigel", f"use fromisoformat ({i})", f"2026-10-01 12:{i:02d}:00"),
            )
    return path


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None
    events = _events_db(tmp_path)
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel", agent_name="rigel", version="1", health_endpoint="/health",
            skills=[SkillDefinition(skill_id=SKILL, description="code", input_schema={}, output_schema={})],
        )
    )
    agent = CapturingAgent()
    nebula = NebulaStore(db_path=str(tmp_path / "nebula.db"))
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"rigel": agent},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        nebula=nebula,
    )
    llm_replies = ['["Prefer datetime.fromisoformat for ISO dates."]']
    llm_calls = []

    def fake_llm(system, user):
        llm_calls.append(user)
        reply = llm_replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(svc, "_andromeda", andromeda)
    monkeypatch.setattr(svc, "_orion_db_path", lambda: events)
    monkeypatch.setattr(svc, "_lesson_llm", fake_llm)
    monkeypatch.setattr(svc, "_lesson_stores", {})
    return SimpleNamespace(
        client=TestClient(svc.app), nebula=nebula, andromeda=andromeda, agent=agent, replies=llm_replies, calls=llm_calls
    )


ROUTES = [
    ("get", "/lessons"),
    ("post", "/lessons/propose"),
    ("post", "/lessons/x/approve"),
    ("post", "/lessons/x/reject"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_lesson_route_requires_the_api_key(env, method, path):
    assert getattr(env.client, method)(path).status_code == 401


def propose(env):
    r = env.client.post("/lessons/propose", headers=AUTH)
    assert r.status_code == 200
    return r.json()["proposed"]


def test_propose_creates_pending_lessons_and_touches_no_memory(env):
    proposed = propose(env)
    assert [p["content"] for p in proposed] == ["Prefer datetime.fromisoformat for ISO dates."]
    assert proposed[0]["status"] == "pending" and proposed[0]["skill_id"] == SKILL
    assert env.nebula.namespaces() == []  # human gate: nothing applied yet
    listed = env.client.get("/lessons", headers=AUTH).json()["lessons"]
    assert [c["candidate_id"] for c in listed] == [proposed[0]["candidate_id"]]


def test_propose_is_a_noop_without_enough_corrections(env):
    propose(env)
    assert propose(env) == []  # all three events are used now
    assert len(env.calls) == 1


def test_propose_honours_min_examples(env):
    r = env.client.post("/lessons/propose", json={"min_examples": 4}, headers=AUTH)
    assert r.json() == {"proposed": []} and env.calls == []
    assert env.client.post("/lessons/propose", json={"min_examples": 0}, headers=AUTH).status_code == 422


def test_propose_survives_an_llm_outage(env):
    env.replies[0] = RuntimeError("provider down")
    assert propose(env) == []
    env.replies[0] = '["Recovered lesson."]'
    assert [p["content"] for p in propose(env)] == ["Recovered lesson."]


def test_approve_writes_one_skill_memory(env):
    candidate = propose(env)[0]
    r = env.client.post(f"/lessons/{candidate['candidate_id']}/approve", json={**REVIEWER, "reviewer_note": "good"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    [entry] = env.nebula.list(f"skill:{SKILL}")
    assert entry.content == "Prefer datetime.fromisoformat for ISO dates."
    assert entry.tags == ["lesson", "agent:rigel"]
    assert str(entry.memory_id) == r.json()["memory_id"]
    assert env.client.get("/lessons", headers=AUTH).json()["lessons"] == []
    approved = env.client.get("/lessons?status=approved", headers=AUTH).json()["lessons"]
    assert approved[0]["memory_id"] == r.json()["memory_id"] and approved[0]["reviewed_by"] == "alice"


def test_approve_with_edited_content(env):
    candidate = propose(env)[0]
    r = env.client.post(
        f"/lessons/{candidate['candidate_id']}/approve", json={**REVIEWER, "content": "  Edited   by a human. "}, headers=AUTH
    )
    assert r.status_code == 200
    assert [e.content for e in env.nebula.list(f"skill:{SKILL}")] == ["Edited by a human."]


@pytest.mark.parametrize("content", ["", "   ", "x" * 301])
def test_approve_rejects_bad_edited_content_without_claiming(env, content):
    candidate = propose(env)[0]
    r = env.client.post(f"/lessons/{candidate['candidate_id']}/approve", json={**REVIEWER, "content": content}, headers=AUTH)
    assert r.status_code == 422
    assert len(env.client.get("/lessons", headers=AUTH).json()["lessons"]) == 1
    assert env.nebula.namespaces() == []


def test_double_approval_and_cross_decisions_conflict(env):
    cid = propose(env)[0]["candidate_id"]
    assert env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH).status_code == 200
    assert env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH).status_code == 409
    assert env.client.post(f"/lessons/{cid}/reject", json=REVIEWER, headers=AUTH).status_code == 409
    assert len(env.nebula.list(f"skill:{SKILL}")) == 1


def test_reject_stores_nothing(env):
    cid = propose(env)[0]["candidate_id"]
    r = env.client.post(f"/lessons/{cid}/reject", json={**REVIEWER, "reviewer_note": "wrong"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert env.nebula.namespaces() == []
    assert env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH).status_code == 409


def test_unknown_candidate_is_404_and_reviewer_is_required(env):
    assert env.client.post("/lessons/nope/approve", json=REVIEWER, headers=AUTH).status_code == 404
    assert env.client.post("/lessons/nope/reject", json=REVIEWER, headers=AUTH).status_code == 404
    cid = propose(env)[0]["candidate_id"]
    assert env.client.post(f"/lessons/{cid}/approve", json={}, headers=AUTH).status_code == 422
    assert env.client.post(f"/lessons/{cid}/approve", json={"reviewed_by": ""}, headers=AUTH).status_code == 422


def test_failed_memory_write_reverts_the_claim(env, monkeypatch):
    cid = propose(env)[0]["candidate_id"]

    def boom(*a, **k):
        raise RuntimeError("disk full")

    original = env.nebula.remember
    monkeypatch.setattr(env.nebula, "remember", boom)
    assert env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH).status_code == 500
    assert [c["status"] for c in env.client.get("/lessons", headers=AUTH).json()["lessons"]] == ["pending"]
    monkeypatch.setattr(env.nebula, "remember", original)
    assert env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH).status_code == 200


def test_list_status_filter_is_validated(env):
    assert env.client.get("/lessons?status=bogus", headers=AUTH).status_code == 422
    assert env.client.get("/lessons?status=all", headers=AUTH).status_code == 200


def test_end_to_end_correction_to_proposal_to_approval_to_prompt(env):
    cid = propose(env)[0]["candidate_id"]
    task = TaskContract(origin="a2a:x", skill=SKILL, payload={"spec": "parse a date"}, confidence_threshold=0.5)
    env.andromeda.route(task=task)
    assert "memory" not in env.agent.contexts[-1]  # unapproved lessons never reach the agent
    env.client.post(f"/lessons/{cid}/approve", json=REVIEWER, headers=AUTH)
    env.andromeda.route(task=task)
    assert [m["content"] for m in env.agent.contexts[-1]["memory"]] == ["Prefer datetime.fromisoformat for ISO dates."]
    # revoking through the existing memory API takes it back out
    memory_id = env.agent.contexts[-1]["memory"][0]["memory_id"]
    assert env.client.delete(f"/memory/{memory_id}", headers=AUTH).status_code in (200, 204)
    env.andromeda.route(task=task)
    assert "memory" not in env.agent.contexts[-1]
