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


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None

    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.task_log import TaskLog
    from core.artifacts.store import ArtifactStore
    from core.goals.store import GoalStore
    from core.pulsar.registry import PulsarRegistry
    from core.contracts import GoalContract, ProjectNode, PlannedTask

    a = Andromeda(registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
                  task_log=TaskLog(db_path=str(tmp_path / "t.db")), agents={},
                  artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
                  goal_store=GoalStore(db_path=str(tmp_path / "g.db")))
    calls = []
    a.goal_runner.resolve_escalated_task = lambda gid, tid, approved: calls.append((gid, tid, approved))
    monkeypatch.setattr(svc, "boot", lambda: a)
    monkeypatch.setattr(svc, "get_aether_client", lambda: FakeAether())

    g = GoalContract(origin="t", objective="x", confidence_threshold=0.6)
    a.goal_store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    t = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    a.goal_store.save_plan(g.goal_id, [p], [t], plan_confidence=0.9, gated=False)
    a.review_queue.enqueue(task_id=str(t.task_id), task_type="s.a", confidence=0.3,
                           payload={}, goal_id=str(g.goal_id))
    with TestClient(svc.app) as client:
        yield client, calls, g.goal_id, t.task_id


def test_approve_resumes_goal(setup):
    client, calls, gid, tid = setup
    r = client.post(f"/review/queue/{tid}/approve", headers=AUTH)
    assert r.status_code == 200
    assert calls == [(gid, tid, True)]


def test_reject_fails_goal_task(setup):
    client, calls, gid, tid = setup
    client.post(f"/review/queue/{tid}/reject", headers=AUTH)
    assert calls == [(gid, tid, False)]
