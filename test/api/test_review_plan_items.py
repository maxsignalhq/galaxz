import uuid

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


class RecordingAether:
    class Redis:
        def ping(self) -> bool:
            return True

    redis = Redis()

    def __init__(self):
        self.events = []

    def publish_event(self, stream, payload):
        self.events.append(payload)

    def close(self):
        pass


class FakeCoordinator:
    def __init__(self):
        self.started = []

    def start(self, goal_id, actor="system"):
        self.started.append(goal_id)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    monkeypatch.setenv("JOB_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(svc, "_job_repository", None)
    svc.app.middleware_stack = None

    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.review_queue import ReviewQueue
    from agents.andromeda.task_log import TaskLog
    from core.artifacts.store import ArtifactStore
    from core.contracts import GoalContract
    from core.goals.store import GoalStore
    from core.nebula.store import NebulaStore
    from core.pulsar.registry import PulsarRegistry

    andromeda = Andromeda(
        registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
        task_log=TaskLog(db_path=str(tmp_path / "t.db")),
        agents={},
        review_queue=ReviewQueue(db_path=str(tmp_path / "r.db")),
        artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
        goal_store=GoalStore(db_path=str(tmp_path / "g.db")),
        nebula=NebulaStore(db_path=str(tmp_path / "n.db")),
    )
    aether = RecordingAether()
    coordinator = FakeCoordinator()
    monkeypatch.setattr(svc, "boot", lambda: andromeda)
    monkeypatch.setattr(svc, "get_aether_client", lambda: aether)
    monkeypatch.setattr(svc, "_goal_coordinator", lambda: coordinator)

    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.6)
    andromeda.goal_store.create_goal(goal)

    def enqueue_plan(goal_id):
        andromeda.review_queue.enqueue(
            task_id=f"plan:{goal_id}", task_type="goal.plan_review", confidence=0.2,
            payload={}, goal_id=str(goal_id),
        )

    with TestClient(svc.app) as client:
        yield client, andromeda, aether, coordinator, goal, enqueue_plan


@pytest.mark.parametrize("action", ["approve", "accept"])
def test_plan_review_approval_starts_goal_and_publishes_valid_feedback(env, action):
    client, _, aether, coordinator, goal, enqueue_plan = env
    enqueue_plan(goal.goal_id)

    r = client.post(f"/review/queue/plan:{goal.goal_id}/{action}", headers=AUTH)

    assert r.status_code == 200
    assert coordinator.started == [goal.goal_id]
    assert len(aether.events) == 1
    # the feedback event carries the goal's UUID, not the "plan:" queue key
    assert uuid.UUID(aether.events[0]["task_id"]) == goal.goal_id


def test_plan_review_rejection_fails_goal_and_publishes_valid_feedback(env):
    client, andromeda, aether, _, goal, enqueue_plan = env
    enqueue_plan(goal.goal_id)

    r = client.post(f"/review/queue/plan:{goal.goal_id}/reject", headers=AUTH)

    assert r.status_code == 200
    assert andromeda.goal_store.get_goal(goal.goal_id).status == "failed"
    assert uuid.UUID(aether.events[0]["task_id"]) == goal.goal_id


def test_review_item_for_missing_goal_can_be_dismissed(env):
    client, andromeda, aether, coordinator, _, enqueue_plan = env
    orphan = uuid.uuid4()
    enqueue_plan(orphan)

    r = client.post(f"/review/queue/plan:{orphan}/approve", headers=AUTH)

    assert r.status_code == 200  # no 500 / KeyError
    assert coordinator.started == []  # nothing to start
    assert client.post(f"/review/queue/plan:{orphan}/approve", headers=AUTH).status_code == 409


def test_review_item_for_missing_goal_reject_is_also_clean(env):
    client, _, _, _, _, enqueue_plan = env
    orphan = uuid.uuid4()
    enqueue_plan(orphan)
    assert client.post(f"/review/queue/plan:{orphan}/reject", headers=AUTH).status_code == 200
