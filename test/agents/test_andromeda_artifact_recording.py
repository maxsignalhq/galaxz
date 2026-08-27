import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore, identity_key
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.pulsar.registry import PulsarRegistry


class FakeArtifactAgent:
    def run(self, skill_id, payload, context):
        # Real agents (e.g. RigelAgent.run()) return a flat dict with no "result" key —
        # _execute_node's result.get("result", result) falls back to the whole dict,
        # which is what carries "artifacts" through to AndromedaState.result.
        return {
            "confidence": 0.9,
            "writable": True,
            "artifacts": [{"filename": "out.py", "content": "x = 1", "language": "python", "artifact_type": "code"}],
        }


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


def test_route_records_produced_artifacts(registry_with_fake_agent, tmp_path):
    artifact_store = ArtifactStore(db_path=str(tmp_path / "artifacts.db"))
    andromeda = Andromeda(
        registry=registry_with_fake_agent,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"fake": FakeArtifactAgent()},
        artifact_store=artifact_store,
    )
    task = TaskContract(
        origin="test",
        skill="fake.skill.echo",
        payload={},
        confidence_threshold=0.5,
    )

    andromeda.route(task=task)

    files = artifact_store.list_files()
    assert len(files) == 1
    assert files[0]["identity_key"] == identity_key("", "out.py")
