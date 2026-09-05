import pytest
from core.contracts import GoalContract, ProjectNode, PlannedTask
from core.goals.store import GoalStore


@pytest.fixture
def store(tmp_path):
    return GoalStore(db_path=str(tmp_path / "goals.db"))


def _goal():
    return GoalContract(origin="test", objective="build X", confidence_threshold=0.65)


def _plan(goal_id):
    p = ProjectNode(goal_id=goal_id, title="proj")
    t1 = PlannedTask(project_id=p.project_id, goal_id=goal_id, skill="s.a", payload={})
    t2 = PlannedTask(project_id=p.project_id, goal_id=goal_id, skill="s.b", payload={}, depends_on=[t1.task_id])
    return [p], [t1, t2]


def test_create_and_get_goal(store):
    g = _goal()
    store.create_goal(g)
    got = store.get_goal(g.goal_id)
    assert got is not None
    assert got.objective == "build X"
    assert got.status == "planning"


def test_save_plan_sets_ready_and_confidence(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    got = store.get_goal(g.goal_id)
    assert got.status == "ready"
    assert got.plan_confidence == 0.8
    tree = store.goal_tree(g.goal_id)
    assert len(tree["projects"]) == 1
    assert len(tree["projects"][0]["tasks"]) == 2
    assert tree["projects"][0]["tasks"][1]["depends_on"] == [str(tasks[0].task_id)]


def test_save_plan_gated_sets_paused(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.3, gated=True)
    assert store.get_goal(g.goal_id).status == "paused"


def test_update_task_and_rollup(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    store.update_task(tasks[0].task_id, status="complete", confidence=0.9)
    store.update_task(tasks[1].task_id, status="complete", confidence=0.7)
    r = store.rollup(g.goal_id)
    assert r == {
        "status": "ready", "completed": 2, "total": 2, "min_confidence": 0.7,
        "blocked": 0, "failed": 0, "escalated": 0, "cancelled": 0,
    }


def test_try_claim_is_single_winner(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    assert store.try_claim(g.goal_id) is True
    assert store.try_claim(g.goal_id) is False
    assert store.get_goal(g.goal_id).status == "running"


def test_list_goals_newest_first(store):
    a, b = _goal(), _goal()
    store.create_goal(a)
    store.create_goal(b)
    ids = [g.goal_id for g in store.list_goals()]
    assert set(ids) == {a.goal_id, b.goal_id}
