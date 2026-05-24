import os
import textwrap

import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry
from workspace.config import WorkspaceConfig, load_workspace_config


# ── Test 1 ──────────────────────────────────────────────────────────────────
def test_disabled_config_accepts_empty_workspace_root():
    cfg = WorkspaceConfig(enabled=False, workspace_root="")
    assert cfg.enabled is False
    assert cfg.workspace_root == ""


# ── Test 2 ──────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_with_valid_path(tmp_path):
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        textwrap.dedent(f"""\
            workspace_root: "{project_dir}"
            enabled: true
        """)
    )

    cfg = load_workspace_config(str(config_file))

    assert cfg.enabled is True
    assert cfg.workspace_root == str(project_dir)


# ── Test 3a ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_empty_root_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text("workspace_root: ''\nenabled: true\n")

    with pytest.raises(ValueError, match="workspace_root must not be empty"):
        load_workspace_config(str(config_file))


# ── Test 3b ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_missing_path_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        "workspace_root: '/does/not/exist/xyz'\nenabled: true\n"
    )

    with pytest.raises(ValueError, match="workspace_root does not exist"):
        load_workspace_config(str(config_file))


# ── Test 3c ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_path_is_file_raises(tmp_path):
    a_file = tmp_path / "somefile.txt"
    a_file.write_text("content")

    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(f"workspace_root: '{a_file}'\nenabled: true\n")

    with pytest.raises(ValueError, match="workspace_root does not exist or is not a directory"):
        load_workspace_config(str(config_file))


# ── Missing file ─────────────────────────────────────────────────────────────
def test_load_workspace_config_missing_file_returns_disabled_default(tmp_path):
    cfg = load_workspace_config(str(tmp_path / "no_such_file.yaml"))

    assert cfg.enabled is False
    assert cfg.workspace_root == ""


# ── Test 4: Andromeda route injects workspace_root into context ───────────────

_SKILL_ID = "workspace.test.skill"


class _MockAgent:
    def __init__(self):
        self.received_context: dict | None = None

    def run(self, skill_id, payload, context=None):
        self.received_context = context
        return {"confidence": 0.9, "result": {"ok": True}}


def _register_mock_agent(registry: PulsarRegistry) -> None:
    registry.register(
        SkillManifest(
            agent_id="mock",
            agent_name="Mock Agent",
            version="0.1.0",
            health_endpoint="http://mock:8080/health",
            skills=[
                SkillDefinition(
                    skill_id=_SKILL_ID,
                    description="Mock skill for workspace injection tests.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            ],
        )
    )


def test_andromeda_route_injects_workspace_root_into_context(tmp_path, monkeypatch):
    ws_path = str(tmp_path / "my-project")
    os.makedirs(ws_path)

    monkeypatch.setattr(
        "agents.andromeda.orchestrator.load_workspace_config",
        lambda: WorkspaceConfig(workspace_root=ws_path, enabled=True),
    )

    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    _register_mock_agent(registry)

    mock_agent = _MockAgent()
    andromeda = Andromeda(registry, task_log, agents={"mock": mock_agent})
    result = andromeda.route(
        task_type="workspace_test",
        required_skills=[_SKILL_ID],
        payload={"x": 1},
    )

    assert result["status"] == "complete"
    assert result["context"]["workspace_root"] == ws_path
    # verify workspace_root actually reached the agent's run() call
    assert mock_agent.received_context is not None
    assert mock_agent.received_context.get("workspace_root") == ws_path


def test_andromeda_route_does_not_inject_when_workspace_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agents.andromeda.orchestrator.load_workspace_config",
        lambda: WorkspaceConfig(workspace_root="", enabled=False),
    )

    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    _register_mock_agent(registry)

    mock_agent = _MockAgent()
    andromeda = Andromeda(registry, task_log, agents={"mock": mock_agent})
    result = andromeda.route(
        task_type="workspace_test",
        required_skills=[_SKILL_ID],
        payload={"x": 1},
    )

    assert result["status"] == "complete"
    assert "workspace_root" not in result["context"]
