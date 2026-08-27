import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.pulsar.registry import PulsarRegistry


class FakeConfidenceAgent:
    def __init__(self, confidence: float):
        self.confidence = confidence

    def run(self, skill_id, payload, context):
        return {"result": {"ok": True}, "confidence": self.confidence}


@pytest.fixture
def registry_with_fake_agent(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="fake",
            agent_name="Fake Agent",
            version="1.0.0",
            skills=[
                SkillDefinition(
                    skill_id="fake.skill.echo",
                    description="echo",
                    input_schema={},
                    output_schema={},
                )
            ],
            health_endpoint="/health",
        )
    )
    return registry


def _route_with_confidence(registry, tmp_path, confidence, confidence_threshold):
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"fake": FakeConfidenceAgent(confidence)},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
    )
    task = TaskContract(
        origin="test",
        skill="fake.skill.echo",
        payload={},
        confidence_threshold=confidence_threshold,
    )
    return andromeda.route(task=task)


def test_task_level_threshold_escalates_despite_clearing_the_global_default(
    registry_with_fake_agent, tmp_path
):
    # 0.70 confidence clears Rigel's global default completion threshold (0.65) but
    # not this task's own stricter 0.90 threshold — the per-task override must win.
    result = _route_with_confidence(
        registry_with_fake_agent, tmp_path, confidence=0.70, confidence_threshold=0.90
    )
    assert result["status"] == "escalated"


def test_task_level_threshold_completes_despite_missing_the_global_default(
    registry_with_fake_agent, tmp_path
):
    # 0.55 confidence misses Rigel's global default completion threshold (0.65) but
    # clears this task's own relaxed 0.50 threshold.
    result = _route_with_confidence(
        registry_with_fake_agent, tmp_path, confidence=0.55, confidence_threshold=0.50
    )
    assert result["status"] == "complete"
