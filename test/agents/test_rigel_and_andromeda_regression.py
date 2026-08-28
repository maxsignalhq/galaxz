import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry


@pytest.fixture
def temp_registry(tmp_path):
    return PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))


def test_rigel_registers_all_skills(temp_registry):
    agent = RigelAgent(temp_registry)

    health = agent.health()
    registered = {skill.skill_id for skill in temp_registry.get_all_skills()}

    assert health["status"] == "ok"
    assert len(health["skills"]) == 6
    assert registered == set(health["skills"])


@pytest.mark.parametrize(
    ("skill_id", "payload", "required_key"),
    [
        (
            "rigel.skill.code_generation",
            {"spec": "Create a safe add function", "language": "python"},
            "code",
        ),
        (
            "rigel.skill.test_writing",
            {"code": "def add(a, b): return a + b", "test_framework": "pytest"},
            "tests",
        ),
        (
            "rigel.skill.debug_triage",
            {"error_trace": "ValueError: bad input", "language": "python"},
            "root_cause_hypothesis",
        ),
        (
            "rigel.skill.pr_review",
            {"diff": "diff --git a/app.py b/app.py\n+password = request.json['password']"},
            "findings",
        ),
        (
            "rigel.skill.refactor",
            {"code": "def add(a,b): return a+b", "refactor_intent": "format", "language": "python"},
            "refactored_code",
        ),
        (
            "rigel.skill.scaffold",
            {"project_type": "cli", "stack": "python", "features": ["health command"]},
            "files",
        ),
    ],
)
def test_rigel_skill_contracts_are_stable(
    temp_registry,
    deterministic_rigel_llm,
    skill_id,
    payload,
    required_key,
):
    agent = RigelAgent(temp_registry)
    agent.llm = deterministic_rigel_llm

    result = agent.run(skill_id, payload)

    assert required_key in result
    assert result["confidence"] >= 0.65
    assert result["confidence_breakdown"]["self_critique"] == 0.92
    assert result["gaps"] == []


def test_andromeda_routes_known_rigel_skill_and_persists_task(
    tmp_path,
    deterministic_rigel_llm,
):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    artifact_store = ArtifactStore(db_path=str(tmp_path / "artifacts.db"))
    andromeda = Andromeda(registry, task_log, artifact_store=artifact_store)
    andromeda._agents["rigel"].llm = deterministic_rigel_llm

    state = andromeda.route(
        task_type="code_generation",
        required_skills=["rigel.skill.code_generation"],
        payload={"spec": "Create a safe add function", "language": "python"},
    )

    assert state["status"] == "complete"
    assert state["assigned_agent"] == "rigel"
    assert state["confidence"] >= 0.65

    persisted = task_log.get(state["task_id"])
    assert persisted is not None
    assert persisted["status"] == "complete"
    assert persisted["assigned_agent"] == "rigel"


def test_andromeda_uses_seed_weight_when_multiple_agents_match(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    artifact_store = ArtifactStore(db_path=str(tmp_path / "artifacts.db"))
    skill = SkillDefinition(
        skill_id="rigel.skill.code_generation",
        description="Generate code",
        input_schema={},
        output_schema={},
        avg_confidence=0.5,
    )
    registry.register(
        SkillManifest(
            agent_id="vega",
            agent_name="Vega",
            version="0.1.0",
            skills=[skill],
            health_endpoint="http://vega/health",
        )
    )
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="0.1.0",
            skills=[skill],
            health_endpoint="http://rigel/health",
        )
    )

    class FakeAgent:
        def __init__(self, agent_id: str):
            self.agent_id = agent_id

        def run(self, skill_id, payload, context):
            return {"result": {"agent_id": self.agent_id}, "confidence": 0.91}

    andromeda = Andromeda(
        registry,
        task_log,
        agents={"vega": FakeAgent("vega"), "rigel": FakeAgent("rigel")},
        artifact_store=artifact_store,
    )

    state = andromeda.route(
        task_type="code_generation",
        required_skills=["rigel.skill.code_generation"],
        payload={"spec": "Create a safe add function", "language": "python"},
    )

    assert state["status"] == "complete"
    assert state["assigned_agent"] == "rigel"
    assert "routing_weight=1.00" in state["assignment_reason"]


def test_andromeda_escalates_when_no_agent_matches(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    artifact_store = ArtifactStore(db_path=str(tmp_path / "artifacts.db"))
    andromeda = Andromeda(registry, task_log, artifact_store=artifact_store)

    state = andromeda.route(
        task_type="unknown",
        required_skills=["unknown.skill.missing"],
        payload={"spec": "cannot route"},
    )

    assert state["status"] == "no_agent_found"
    assert state["failure_reason"] == "no_skill_match"
