import uuid
import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


class FakeAether:
    class Redis:
        def ping(self) -> bool:
            return True

    redis = Redis()

    def publish_event(self, *a, **k):
        pass

    def close(self):
        pass


def _build_andromeda(tmp_path):
    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.task_log import TaskLog
    from agents.andromeda.planner import PlanResult
    from core.artifacts.store import ArtifactStore
    from core.goals.store import GoalStore
    from core.pulsar.registry import PulsarRegistry
    from core.contracts import SkillDefinition, SkillManifest, ProjectNode, PlannedTask

    reg = PulsarRegistry(db_path=str(tmp_path / "p.db"))
    reg.register(SkillManifest(
        agent_id="rigel", agent_name="Rigel", version="1.0.0",
        skills=[SkillDefinition(skill_id="rigel.skill.code_generation", description="gen",
                                input_schema={}, output_schema={})],
        health_endpoint="/health"))
    a = Andromeda(registry=reg, task_log=TaskLog(db_path=str(tmp_path / "t.db")),
                  agents={}, artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
                  goal_store=GoalStore(db_path=str(tmp_path / "g.db")))

    def fake_plan(goal, _conf=[0.9]):
        p = ProjectNode(goal_id=goal.goal_id, title="proj")
        t = PlannedTask(project_id=p.project_id, goal_id=goal.goal_id,
                        skill="rigel.skill.code_generation", payload={"spec": "x"})
        return PlanResult(projects=[p], tasks=[t], plan_confidence=a._plan_conf)

    a._plan_conf = 0.9
    a.goal_planner.plan = fake_plan
    a.goal_runner.run_async = lambda gid: None
    return a


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None
    a = _build_andromeda(tmp_path)
    monkeypatch.setattr(svc, "boot", lambda: a)
    monkeypatch.setattr(svc, "get_aether_client", lambda: FakeAether())
    with TestClient(svc.app) as c:
        c._andromeda = a
        yield c


def test_post_goal_returns_202_and_tree(client):
    r = client.post("/goals", json={"objective": "build a todo API"}, headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert body["goal"]["objective"] == "build a todo API"
    assert len(body["projects"][0]["tasks"]) == 1
    assert body["plan_pending_review"] is False


def test_post_goal_low_plan_confidence_is_gated(client):
    client._andromeda._plan_conf = 0.2
    r = client.post("/goals", json={"objective": "vague", "confidence_threshold": 0.65}, headers=AUTH)
    assert r.status_code == 202
    assert r.json()["plan_pending_review"] is True
    assert r.json()["goal"]["status"] == "paused"


def test_get_goal_404(client):
    assert client.get(f"/goals/{uuid.uuid4()}", headers=AUTH).status_code == 404


def test_get_and_list_goal(client):
    gid = client.post("/goals", json={"objective": "x"}, headers=AUTH).json()["goal"]["goal_id"]
    got = client.get(f"/goals/{gid}", headers=AUTH)
    assert got.status_code == 200
    assert "rollup" in got.json()
    assert any(g["goal_id"] == gid for g in client.get("/goals", headers=AUTH).json())


def test_resume_409_when_running(client):
    gid = client.post("/goals", json={"objective": "x"}, headers=AUTH).json()["goal"]["goal_id"]
    client._andromeda.goal_store.set_goal_status(uuid.UUID(gid), "running")
    assert client.post(f"/goals/{gid}/resume", headers=AUTH).status_code == 409


def test_goals_route_requires_auth(client):
    assert client.post("/goals", json={"objective": "x"}).status_code == 401
