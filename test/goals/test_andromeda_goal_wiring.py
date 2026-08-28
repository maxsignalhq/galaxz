from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.andromeda.goal_runner import GoalRunner
from core.artifacts.store import ArtifactStore
from core.goals.store import GoalStore
from core.pulsar.registry import PulsarRegistry


def test_andromeda_exposes_goal_components(tmp_path):
    a = Andromeda(
        registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
        task_log=TaskLog(db_path=str(tmp_path / "t.db")),
        agents={},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
        goal_store=GoalStore(db_path=str(tmp_path / "g.db")),
    )
    assert isinstance(a.goal_store, GoalStore)
    assert isinstance(a.goal_runner, GoalRunner)
    assert a.goal_planner is not None
