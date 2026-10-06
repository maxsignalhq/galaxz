import uuid

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.goals.store import GoalStore
from core.policy import REQUIRE_REVIEW, GrantStore, PolicyEngine, PolicyRule, payload_digest
from core.pulsar.registry import PulsarRegistry

AUTH = {"Authorization": "Bearer test-key"}
SKILL = "fake.skill.echo"
ORIGIN = "a2a:x"
PAYLOAD = {"text": "hi"}


class FakeAether:
    class Redis:
        def ping(self) -> bool:
            return True

    redis = Redis()

    def publish_event(self, *a, **k):
        pass

    def close(self):
        pass


class FakeCoordinator:
    def __init__(self):
        self.reruns = []
        self.fail_with = None

    def rerun(self, goal_id, task_id, *, actor, reason=None):
        if self.fail_with:
            raise self.fail_with
        self.reruns.append((goal_id, task_id, actor, reason))

    def start(self, *a, **k):
        raise AssertionError("a held task must be rerun, not resumed as complete")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    monkeypatch.setenv("JOB_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(svc, "_job_repository", None)
    svc.app.middleware_stack = None
    grants = GrantStore(str(tmp_path / "policy.db"))
    andromeda = Andromeda(
        registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
        task_log=TaskLog(db_path=str(tmp_path / "t.db")),
        agents={},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
        goal_store=GoalStore(db_path=str(tmp_path / "g.db")),
        policy=PolicyEngine((PolicyRule("fake.*", REQUIRE_REVIEW),)),
        policy_grants=grants,
    )
    coordinator = FakeCoordinator()
    monkeypatch.setattr(svc, "boot", lambda: andromeda)
    monkeypatch.setattr(svc, "get_aether_client", lambda: FakeAether())
    monkeypatch.setattr(svc, "_goal_coordinator", lambda: coordinator)
    with TestClient(svc.app) as client:
        yield client, andromeda, grants, coordinator


def hold_item(andromeda, **extra):
    task_id = str(uuid.uuid4())
    andromeda.review_queue.enqueue(
        task_id=task_id,
        task_type="echo",
        confidence=0.0,
        payload=PAYLOAD,
        skill_id=SKILL,
        agent_output={
            "policy_hold": {
                "origin": ORIGIN,
                "skill": SKILL,
                "digest": payload_digest(ORIGIN, SKILL, PAYLOAD),
                "reason": "needs a human",
                "rule_index": 0,
            }
        },
        **extra,
    )
    return task_id


def grant_available(grants):
    return grants.consume(origin=ORIGIN, skill=SKILL, digest=payload_digest(ORIGIN, SKILL, PAYLOAD))


@pytest.mark.parametrize("action", ["approve", "accept"])
def test_approving_a_held_task_issues_one_grant(env, action):
    client, andromeda, grants, _ = env
    task_id = hold_item(andromeda)
    assert client.post(f"/review/queue/{task_id}/{action}", headers=AUTH).status_code == 200
    assert grant_available(grants) is True
    assert grant_available(grants) is False


def test_rejecting_a_held_task_issues_no_grant(env):
    client, andromeda, grants, _ = env
    task_id = hold_item(andromeda)
    assert client.post(f"/review/queue/{task_id}/reject", headers=AUTH).status_code == 200
    assert grant_available(grants) is False


def test_reapproving_does_not_issue_a_second_grant(env):
    client, andromeda, grants, _ = env
    task_id = hold_item(andromeda)
    client.post(f"/review/queue/{task_id}/approve", headers=AUTH)
    assert client.post(f"/review/queue/{task_id}/approve", headers=AUTH).status_code == 409
    assert grant_available(grants) is True
    assert grant_available(grants) is False


def test_ordinary_review_items_issue_no_grant(env):
    client, andromeda, grants, _ = env
    task_id = str(uuid.uuid4())
    andromeda.review_queue.enqueue(
        task_id=task_id, task_type="echo", confidence=0.3, payload=PAYLOAD, agent_output={"result": "x"}
    )
    assert client.post(f"/review/queue/{task_id}/approve", headers=AUTH).status_code == 200
    assert grant_available(grants) is False


def test_malformed_hold_record_issues_no_grant(env):
    client, andromeda, grants, _ = env
    task_id = str(uuid.uuid4())
    andromeda.review_queue.enqueue(
        task_id=task_id,
        task_type="echo",
        confidence=0.0,
        payload=PAYLOAD,
        agent_output={"policy_hold": {"origin": ORIGIN, "skill": SKILL}},  # no digest
    )
    assert client.post(f"/review/queue/{task_id}/approve", headers=AUTH).status_code == 200
    assert grant_available(grants) is False


def test_approving_a_held_goal_task_reruns_it_instead_of_completing_it(env):
    client, andromeda, grants, coordinator = env
    goal_id, planned_id = uuid.uuid4(), uuid.uuid4()
    task_id = hold_item(andromeda, goal_id=str(goal_id), planned_task_id=str(planned_id))
    # _resume_goal_from_review must not run for a held task: it would mark it complete.
    assert client.post(f"/review/queue/{task_id}/approve", headers=AUTH).status_code == 200
    assert coordinator.reruns == [(goal_id, planned_id, "review", "policy hold approved")]
    assert grant_available(grants) is True


def test_a_failed_rerun_does_not_break_approval(env):
    client, andromeda, grants, coordinator = env
    coordinator.fail_with = ValueError("task is running, cannot rerun")
    task_id = hold_item(andromeda, goal_id=str(uuid.uuid4()), planned_task_id=str(uuid.uuid4()))
    assert client.post(f"/review/queue/{task_id}/approve", headers=AUTH).status_code == 200
    assert grant_available(grants) is True


def test_hold_approve_resubmit_runs_the_task_once_end_to_end(env):
    from core.contracts import SkillDefinition, SkillManifest, TaskContract

    client, andromeda, _, _ = env
    calls = []

    class Agent:
        def run(self, skill_id, payload, context):
            calls.append(payload)
            return {"result": {"ok": True}, "confidence": 0.95}

    andromeda.registry.register(
        SkillManifest(
            agent_id="fake",
            agent_name="fake",
            version="1",
            health_endpoint="/health",
            skills=[SkillDefinition(skill_id=SKILL, description="echo", input_schema={}, output_schema={})],
        )
    )
    andromeda._agents["fake"] = Agent()

    def submit():
        return andromeda.route(
            task=TaskContract(origin=ORIGIN, skill=SKILL, payload=PAYLOAD, confidence_threshold=0.5)
        )

    held = submit()
    assert held["status"] == "escalated" and calls == []
    assert client.post(f"/review/queue/{held['task_id']}/approve", headers=AUTH).status_code == 200
    assert submit()["status"] == "complete" and calls == [PAYLOAD]
    assert submit()["status"] == "escalated" and calls == [PAYLOAD]  # the grant was single-use
