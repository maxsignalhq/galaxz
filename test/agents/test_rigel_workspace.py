import json
from pathlib import Path
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
    assert Path(wa["absolute_path"]).exists()
    assert wa["filename"] == "output.py"
    assert Path(wa["absolute_path"]).read_text().endswith("\n")
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix == ".py") == ["output.py"]
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


@pytest.mark.parametrize("filename,code", [
    ("output.py", "api_key = 'abcdefghijklmnop'"),
    ("payload.zip", "print('ok')"),
])
def test_artifact_scan_prevents_writes_and_execution(rigel, tmp_path, monkeypatch, filename, code):
    from core.security.artifact_scan import ArtifactSafetyError

    rigel.config.execution_calibration_enabled = True
    rigel.llm = lambda **kwargs: code
    existing = tmp_path / filename
    existing.write_text("original")

    def unexpected_execution(**kwargs):
        pytest.fail("unsafe artifact reached execution")

    monkeypatch.setattr("agents.rigel.agent.execute_generated_output", unexpected_execution)
    with pytest.raises(ArtifactSafetyError):
        rigel.run(
            "rigel.skill.code_generation", {"spec": "generate"},
            context={"workspace_root": str(tmp_path), "output_path": filename},
        )
    assert existing.read_text() == "original"


def test_scaffold_scan_checks_all_files_before_first_write(rigel, tmp_path):
    from core.security.artifact_scan import ArtifactSafetyError

    rigel.llm = lambda **kwargs: json.dumps({
        "file_tree": {}, "instructions": "", "files": [
            {"path": "safe.py", "content": "x = 1"},
            {"path": "secret.py", "content": "api_key = 'abcdefghijklmnop'"},
        ],
    })
    with pytest.raises(ArtifactSafetyError):
        rigel.run("rigel.skill.scaffold", {"project_type": "app", "stack": "python"},
                  context={"workspace_root": str(tmp_path)})
    assert not (tmp_path / "safe.py").exists()
    assert not (tmp_path / "secret.py").exists()
