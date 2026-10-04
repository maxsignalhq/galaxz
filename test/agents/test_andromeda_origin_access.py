import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.pulsar.registry import PulsarRegistry


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def run(self, skill_id, payload, context):
        self.calls += 1
        return {"result": {"ok": True}, "confidence": 0.95}


def _skill(allowed_origins=None, skill_id="fake.skill.echo"):
    return SkillDefinition(
        skill_id=skill_id,
        description="echo",
        input_schema={},
        output_schema={},
        allowed_origins=allowed_origins,
    )


def _setup(tmp_path, *manifests):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agents = {}
    for agent_id, skills in manifests:
        registry.register(
            SkillManifest(
                agent_id=agent_id,
                agent_name=agent_id,
                version="1.0.0",
                skills=skills,
                health_endpoint="/health",
            )
        )
        agents[agent_id] = FakeAgent()
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents=agents,
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
    )
    return andromeda, agents


def _route(andromeda, origin, skill="fake.skill.echo"):
    return andromeda.route(
        task=TaskContract(origin=origin, skill=skill, payload={}, confidence_threshold=0.5)
    )


def test_manifest_without_allowed_origins_stays_open(tmp_path):
    andromeda, agents = _setup(tmp_path, ("fake", [_skill()]))
    assert _route(andromeda, "anyone")["status"] == "complete"
    assert agents["fake"].calls == 1


def test_disallowed_origin_is_rejected_before_dispatch(tmp_path):
    andromeda, agents = _setup(tmp_path, ("fake", [_skill(["ops"])]))
    result = _route(andromeda, "intruder")
    assert result["status"] == "no_agent_found"
    assert result["failure_reason"] == "origin_not_allowed"
    assert agents["fake"].calls == 0


def test_allowed_origin_exact_and_glob(tmp_path):
    andromeda, _ = _setup(tmp_path, ("fake", [_skill(["ops", "goal:*"])]))
    assert _route(andromeda, "ops")["status"] == "complete"
    assert _route(andromeda, "goal:1234")["status"] == "complete"
    assert _route(andromeda, "opsx")["failure_reason"] == "origin_not_allowed"


def test_empty_allowlist_denies_everyone(tmp_path):
    andromeda, agents = _setup(tmp_path, ("fake", [_skill([])]))
    assert _route(andromeda, "ops")["failure_reason"] == "origin_not_allowed"
    assert agents["fake"].calls == 0


def test_other_agent_without_restriction_still_serves_the_skill(tmp_path):
    andromeda, agents = _setup(
        tmp_path,
        ("locked", [_skill(["ops"])]),
        ("open", [_skill()]),
    )
    result = _route(andromeda, "intruder")
    assert result["status"] == "complete"
    assert result["assigned_agent"] == "open"
    assert agents["locked"].calls == 0


def test_unknown_skill_keeps_no_skill_match_reason(tmp_path):
    andromeda, _ = _setup(tmp_path, ("fake", [_skill(["ops"])]))
    result = _route(andromeda, "intruder", skill="nobody.skill.here")
    assert result["status"] == "no_agent_found"
    assert result["failure_reason"] == "no_skill_match"


def test_allowed_origins_round_trips_through_registry(tmp_path):
    andromeda, _ = _setup(tmp_path, ("fake", [_skill(["ops"])]))
    reloaded = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    skill = reloaded.get_agent("fake").skills[0]
    assert skill.allowed_origins == ["ops"]


def test_permits_helper():
    assert _skill().permits("x") is True
    assert _skill(["a*"]).permits("abc") is True
    assert _skill(["a*"]).permits("b") is False
    assert _skill([]).permits("a") is False
