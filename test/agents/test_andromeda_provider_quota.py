import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.llm.provider import LLMQuotaError
from core.pulsar.registry import PulsarRegistry


class RaisingAgent:
    def __init__(self, exc: Exception):
        self.exc = exc

    def run(self, skill_id, payload, context):
        raise self.exc


@pytest.fixture
def registry(tmp_path):
    reg = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    reg.register(
        SkillManifest(
            agent_id="fake", agent_name="Fake", version="1.0.0",
            skills=[SkillDefinition(
                skill_id="fake.skill.echo", description="echo",
                input_schema={}, output_schema={},
            )],
            health_endpoint="/health",
        )
    )
    return reg


def _route(registry, tmp_path, exc):
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"fake": RaisingAgent(exc)},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
    )
    task = TaskContract(origin="test", skill="fake.skill.echo", payload={}, confidence_threshold=0.65)
    return andromeda, andromeda.route(task=task)


def test_quota_error_fails_cleanly_without_a_review_item(registry, tmp_path):
    andromeda, result = _route(registry, tmp_path, LLMQuotaError("429"))
    assert result["status"] == "failed"
    assert result["failure_reason"] == "provider_quota"
    assert andromeda.review_queue.get_by_task_id(result["task_id"]) is None


def test_other_errors_still_escalate(registry, tmp_path):
    _, result = _route(registry, tmp_path, RuntimeError("boom"))
    assert result["status"] == "escalated"
    assert result["failure_reason"] == "boom"
