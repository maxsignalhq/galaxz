from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from agents.rigel.config import RigelConfig
from core.artifacts.store import ArtifactStore
from core.contracts import GoalContract
from core.contracts import TaskContract
from core.goals.store import GoalStore
from core.pulsar.registry import PulsarRegistry
from workspace.config import WorkspaceConfig


def test_goal_files_stay_in_persisted_folder_after_settings_change(tmp_path, monkeypatch):
    registry = PulsarRegistry(db_path=str(tmp_path / "registry.db"))
    goals = GoalStore(str(tmp_path / "goals.db"))
    agent = RigelAgent(registry, rigel_config=RigelConfig(execution_calibration_enabled=False))
    agent.llm = lambda **kwargs: (
        '{"score": 0.95, "gaps": []}' if "Rate whether" in kwargs["user"] else
        '{"filename": "echo.html", "code": "<p>Echo</p>"}'
    )
    router = Andromeda(registry, TaskLog(str(tmp_path / "tasks.db")), agents={"rigel": agent},
                       artifact_store=ArtifactStore(str(tmp_path / "artifacts.db")), goal_store=goals)
    monkeypatch.setattr("agents.andromeda.orchestrator.load_workspace_config",
                        lambda: WorkspaceConfig(enabled=True, workspace_root=str(tmp_path / "new-setting")))
    for name in ("goal-one", "goal-two"):
        goal = GoalContract(origin="test", objective="echo webpage", confidence_threshold=0.65,
                            workspace_root=str(tmp_path / name))
        goals.create_goal(goal)
        result = router.route(task=TaskContract(
            origin=f"goal:{goal.goal_id}", skill="rigel.skill.code_generation",
            payload={"spec": "echo", "language": "html"}, confidence_threshold=0.65,
            workspace_root=goal.workspace_root,
        ))
        assert result["status"] == "complete"
        assert result["context"]["workspace_root"] == str(tmp_path / name)
        assert (tmp_path / name / "echo.html").read_text() == "<p>Echo</p>\n"
    assert not (tmp_path / "echo.html").exists()
    assert not (tmp_path / "new-setting").exists()
