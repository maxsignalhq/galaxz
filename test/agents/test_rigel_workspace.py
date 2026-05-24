import json
from uuid import uuid4
import pytest
from agents.rigel.agent import RigelAgent
from agents.rigel.config import RigelConfig
from core.pulsar.registry import PulsarRegistry


def _mock_llm(system: str, user: str) -> str:
    if "Rate whether this output fully satisfies the task" in user:
        return json.dumps({"score": 0.85, "gaps": []})
    return "def add(a, b):\n    return a + b\n"


@pytest.fixture
def rigel(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = RigelAgent(registry, rigel_config=RigelConfig(execution_calibration_enabled=False))
    agent.llm = _mock_llm
    return agent


def test_rigel_writes_artifact_to_disk_when_workspace_root_set(rigel, tmp_path):
    result = rigel.run(
        "rigel.skill.code_generation",
        {"spec": "create add function", "language": "python"},
        context={"workspace_root": str(tmp_path), "task_id": str(uuid4())},
    )
    assert len(result["written_artifacts"]) >= 1
    wa = result["written_artifacts"][0]
    assert wa["absolute_path"]
    from pathlib import Path
    assert Path(wa["absolute_path"]).exists()
    # in-memory artifacts unchanged
    assert len(result["artifacts"]) >= 1
    assert result["artifacts"][0]["content"]


def test_rigel_written_artifacts_empty_when_no_workspace_root(rigel, tmp_path):
    result = rigel.run(
        "rigel.skill.code_generation",
        {"spec": "create add function", "language": "python"},
        context={"task_id": str(uuid4())},
    )
    assert result["written_artifacts"] == []
    # artifacts still present in-memory
    assert len(result["artifacts"]) >= 1
