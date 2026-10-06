import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import NebulaStore
from core.policy import DENY, REQUIRE_REVIEW, GrantStore, PolicyEngine, PolicyRule, payload_digest
from core.pulsar.registry import PulsarRegistry

SKILL = "fake.skill.echo"


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def run(self, skill_id, payload, context):
        self.calls += 1
        return {"result": {"ok": True}, "confidence": 0.95}


@pytest.fixture
def make(tmp_path):
    def build(*rules):
        registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
        registry.register(
            SkillManifest(
                agent_id="fake",
                agent_name="fake",
                version="1",
                health_endpoint="/health",
                skills=[SkillDefinition(skill_id=SKILL, description="echo", input_schema={}, output_schema={})],
            )
        )
        agent = FakeAgent()
        grants = GrantStore(str(tmp_path / "policy.db"))
        andromeda = Andromeda(
            registry=registry,
            review_queue=ReviewQueue(db_path=str(tmp_path / "reviews.db")),
            task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
            agents={"fake": agent},
            artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
            nebula=NebulaStore(db_path=str(tmp_path / "nebula.db")),
            policy=PolicyEngine(tuple(rules)),
            policy_grants=grants,
        )
        return andromeda, agent, grants

    return build


def route(andromeda, origin="a2a:x", payload=None, skill=SKILL):
    return andromeda.route(
        task=TaskContract(origin=origin, skill=skill, payload=payload or {"text": "hi"}, confidence_threshold=0.5)
    )


def test_empty_policy_changes_nothing(make):
    andromeda, agent, _ = make()
    assert route(andromeda)["status"] == "complete"
    assert agent.calls == 1


def test_deny_rejects_without_running_the_agent(make):
    andromeda, agent, _ = make(PolicyRule("fake.*", DENY, reason="no fake tools"))
    result = route(andromeda)
    assert result["status"] == "no_agent_found"
    assert result["failure_reason"] == "policy_denied"
    assert result["gaps"] == ["no fake tools"]
    assert agent.calls == 0


def test_deny_is_scoped_by_origin(make):
    andromeda, agent, _ = make(PolicyRule("fake.*", DENY, origin="a2a:*"))
    assert route(andromeda, origin="a2a:partner")["failure_reason"] == "policy_denied"
    assert route(andromeda, origin="goal:1")["status"] == "complete"
    assert agent.calls == 1


def test_require_review_holds_in_the_review_queue_without_running(make):
    andromeda, agent, _ = make(PolicyRule("fake.*", REQUIRE_REVIEW, reason="needs a human"))
    result = route(andromeda, payload={"text": "x"})
    assert result["status"] == "escalated"
    assert result["escalated_to_human"] is True
    assert result["failure_reason"] == "policy_requires_review"
    assert result["review_pending"] is True
    assert agent.calls == 0
    item = andromeda.review_queue.get_by_task_id(result["task_id"])
    hold = item["agent_output"]["policy_hold"]
    assert hold["origin"] == "a2a:x" and hold["skill"] == SKILL and hold["reason"] == "needs a human"
    assert hold["digest"] == payload_digest("a2a:x", SKILL, {"text": "x"})


def test_a_grant_lets_exactly_one_identical_submission_through(make):
    andromeda, agent, grants = make(PolicyRule("fake.*", REQUIRE_REVIEW))
    held = route(andromeda, payload={"text": "x"})
    assert held["status"] == "escalated"
    grants.issue(origin="a2a:x", skill=SKILL, digest=payload_digest("a2a:x", SKILL, {"text": "x"}))
    assert route(andromeda, payload={"text": "x"})["status"] == "complete"
    assert agent.calls == 1
    assert route(andromeda, payload={"text": "x"})["status"] == "escalated"  # grant was single-use
    assert agent.calls == 1


def test_a_grant_does_not_cover_a_different_payload_or_origin(make):
    andromeda, agent, grants = make(PolicyRule("fake.*", REQUIRE_REVIEW))
    grants.issue(origin="a2a:x", skill=SKILL, digest=payload_digest("a2a:x", SKILL, {"text": "x"}))
    assert route(andromeda, payload={"text": "changed"})["status"] == "escalated"
    assert route(andromeda, origin="a2a:other", payload={"text": "x"})["status"] == "escalated"
    assert agent.calls == 0


def test_deny_takes_precedence_over_an_existing_grant(make):
    andromeda, agent, grants = make(PolicyRule("fake.*", DENY))
    grants.issue(origin="a2a:x", skill=SKILL, digest=payload_digest("a2a:x", SKILL, {"text": "hi"}))
    assert route(andromeda)["failure_reason"] == "policy_denied"
    assert agent.calls == 0


def test_unmatched_skills_are_unaffected_by_rules(make):
    andromeda, agent, _ = make(PolicyRule("other.*", DENY))
    assert route(andromeda)["status"] == "complete"
    assert agent.calls == 1


def test_default_andromeda_loads_policy_from_config_and_creates_no_database(tmp_path, monkeypatch):
    (tmp_path / "policy.yaml").write_text("rules:\n  - {skill: 'fake.*', action: deny}\n")
    monkeypatch.setenv("GALAXZ_POLICY_PATH", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB_PATH", str(tmp_path / "data" / "policy.db"))
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    andromeda = Andromeda(
        registry=registry,
        review_queue=ReviewQueue(db_path=str(tmp_path / "reviews.db")),
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        nebula=NebulaStore(db_path=str(tmp_path / "nebula.db")),
    )
    assert andromeda.policy.enabled is True
    assert not (tmp_path / "data" / "policy.db").exists()  # grants DB is lazy
