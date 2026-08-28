import pytest
from core.contracts import GoalContract, ProjectNode, PlannedTask
from core.goals.store import GoalStore
from agents.andromeda.goal_runner import GoalRunner


class FakeReviewQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)


class FakeAndromeda:
    def __init__(self, script):
        self._script = script
        self.review_queue = FakeReviewQueue()
        self.calls = []

    def route(self, task=None):
        self.calls.append(task.skill)
        return dict(self._script[task.skill])


@pytest.fixture
def store(tmp_path):
    return GoalStore(db_path=str(tmp_path / "goals.db"))


def _seed(store, deps_second_on_first=True, threshold=0.65):
    g = GoalContract(origin="t", objective="x", confidence_threshold=threshold)
    store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    t1 = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    d = [t1.task_id] if deps_second_on_first else []
    t2 = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.b", payload={}, depends_on=d)
    store.save_plan(g.goal_id, [p], [t1, t2], plan_confidence=0.9, gated=False)
    return g, t1, t2


def test_linear_chain_completes(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "complete", "confidence": 0.9},
        "s.b": {"status": "complete", "confidence": 0.8},
    })
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == ["s.a", "s.b"]
    assert store.get_goal(g.goal_id).status == "complete"
    assert [t.status for t in store.get_tasks(g.goal_id)] == ["complete", "complete"]


def test_failure_pauses_goal_and_enqueues_review(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "escalated", "confidence": 0.3, "review_pending": True},
        "s.b": {"status": "complete", "confidence": 0.9},
    })
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == ["s.a"]
    assert store.get_goal(g.goal_id).status == "paused"
    tasks = store.get_tasks(g.goal_id)
    assert tasks[0].status == "escalated"
    assert andro.review_queue.enqueued[0]["goal_id"] == str(g.goal_id)


def test_hard_failure_fails_goal(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({"s.a": {"status": "no_agent_found", "confidence": 0.0}})
    GoalRunner(andro, store).run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "failed"


def test_subthreshold_complete_is_escalation(store):
    g, t1, t2 = _seed(store, threshold=0.9)
    andro = FakeAndromeda({"s.a": {"status": "complete", "confidence": 0.7}})
    GoalRunner(andro, store).run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "paused"
    assert store.get_tasks(g.goal_id)[0].status == "escalated"


def test_run_is_not_reentrant(store):
    g, t1, t2 = _seed(store)
    store.try_claim(g.goal_id)
    andro = FakeAndromeda({"s.a": {"status": "complete", "confidence": 0.9}})
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == []


def test_resume_after_approve_continues(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "escalated", "confidence": 0.3, "review_pending": True},
        "s.b": {"status": "complete", "confidence": 0.9},
    })
    runner = GoalRunner(andro, store)
    runner.run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "paused"
    runner.resolve_escalated_task(g.goal_id, t1.task_id, approved=True)
    assert store.get_goal(g.goal_id).status == "complete"
    assert andro.calls == ["s.a", "s.b"]


def test_diamond_dag_runs_all_nodes(store):
    g = GoalContract(origin="t", objective="x", confidence_threshold=0.5)
    store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    a = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    b = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.b", payload={}, depends_on=[a.task_id])
    c = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.c", payload={}, depends_on=[a.task_id])
    d = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.d", payload={}, depends_on=[b.task_id, c.task_id])
    store.save_plan(g.goal_id, [p], [a, b, c, d], plan_confidence=0.9, gated=False)
    andro = FakeAndromeda({k: {"status": "complete", "confidence": 0.9} for k in ["s.a", "s.b", "s.c", "s.d"]})
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls[0] == "s.a"
    assert andro.calls[-1] == "s.d"
    assert set(andro.calls) == {"s.a", "s.b", "s.c", "s.d"}
    assert store.get_goal(g.goal_id).status == "complete"
