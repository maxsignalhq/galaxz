from __future__ import annotations

from uuid import uuid4

import pytest

from core.contracts import GoalContract
from core.contracts import PlannedTask
from core.contracts import ProjectNode
from core.goals import DurableGoalCoordinator
from core.goals import GoalStore
from core.goals import PayloadResolutionError
from core.goals import resolve_payload
from core.jobs import SqliteJobRepository


def _setup(tmp_path, *, limit: int = 4):
    store = GoalStore(str(tmp_path / "goals.db"))
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    goal = GoalContract(origin="test", objective="durable DAG", confidence_threshold=0.65)
    project = ProjectNode(goal_id=goal.goal_id, title="project")
    store.create_goal(goal)
    coordinator = DurableGoalCoordinator(store, jobs, per_goal_limit=limit)
    return store, jobs, coordinator, goal, project


def _complete(jobs, job, confidence: float = 0.9, result: dict | None = None) -> None:
    claimed = jobs.claim(worker_id="test-worker", lease_seconds=30)
    assert claimed is not None and claimed[0].job_id == job.job_id
    jobs.complete(
        job_id=job.job_id,
        lease_token=claimed[1].lease_token,
        output_ref=f"output:{job.job_id}",
        result={"status": "complete", "confidence": confidence, "result": result or {}},
    )


def test_restart_reconciliation_advances_persisted_dag(tmp_path) -> None:
    store, jobs, coordinator, goal, project = _setup(tmp_path)
    first = PlannedTask(
        project_id=project.project_id, goal_id=goal.goal_id,
        skill="rigel.skill.code_generation", payload={"value": "first"},
    )
    second = PlannedTask(
        project_id=project.project_id, goal_id=goal.goal_id,
        skill="vega.skill.test_writing", payload={"value": "second"},
        depends_on=[first.task_id],
    )
    store.save_plan(goal.goal_id, [project], [first, second], 0.9, gated=False)
    coordinator.start(goal.goal_id)
    first_job = jobs.get_job_by_idempotency_key(coordinator.key(goal.goal_id, first.task_id))
    assert first_job is not None
    _complete(jobs, first_job, result={"code": "hello"})

    restarted = DurableGoalCoordinator(
        GoalStore(str(tmp_path / "goals.db")),
        SqliteJobRepository(tmp_path / "jobs.db"),
    )
    restarted.reconcile_all()
    second_job = jobs.get_job_by_idempotency_key(coordinator.key(goal.goal_id, second.task_id))
    assert second_job is not None
    _complete(jobs, second_job)
    restarted.reconcile_all()

    assert restarted.store.get_goal(goal.goal_id).status == "complete"
    assert [task.status for task in restarted.store.get_tasks(goal.goal_id)] == [
        "complete", "complete"
    ]


def test_independent_branches_enqueue_together_and_failure_blocks_only_descendant(tmp_path) -> None:
    store, jobs, coordinator, goal, project = _setup(tmp_path)
    left = PlannedTask(project_id=project.project_id, goal_id=goal.goal_id, skill="s.left", payload={})
    right = PlannedTask(project_id=project.project_id, goal_id=goal.goal_id, skill="s.right", payload={})
    child = PlannedTask(
        project_id=project.project_id, goal_id=goal.goal_id, skill="s.child", payload={},
        depends_on=[left.task_id],
    )
    store.save_plan(goal.goal_id, [project], [left, right, child], 0.9, gated=False)
    coordinator.start(goal.goal_id)
    assert [task.status for task in store.get_tasks(goal.goal_id)] == [
        "running", "running", "pending"
    ]
    left_job = jobs.get_job_by_idempotency_key(coordinator.key(goal.goal_id, left.task_id))
    claimed = jobs.claim(worker_id="worker", lease_seconds=30)
    assert claimed is not None and claimed[0].job_id == left_job.job_id
    jobs.fail(job_id=left_job.job_id, lease_token=claimed[1].lease_token, error="boom")
    coordinator.reconcile(goal.goal_id)
    statuses = {task.task_id: task.status for task in store.get_tasks(goal.goal_id)}
    assert statuses[left.task_id] == "failed"
    assert statuses[child.task_id] == "blocked"
    assert statuses[right.task_id] == "running"


def test_dependency_result_substitution_is_immutable_and_restricted(tmp_path) -> None:
    goal_id = uuid4()
    project_id = uuid4()
    upstream = PlannedTask(
        project_id=project_id, goal_id=goal_id, skill="up", payload={},
        status="complete", result={"artifact": {"path": "build/output.py"}},
    )
    downstream = PlannedTask(
        project_id=project_id, goal_id=goal_id, skill="down",
        payload={"nested": [{"path": f"${{{{ dependencies.{upstream.task_id}.result.artifact.path }}}}"}]},
        depends_on=[upstream.task_id],
    )
    resolved = resolve_payload(downstream, {upstream.task_id: upstream})
    assert resolved == {"nested": [{"path": "build/output.py"}]}
    upstream.result["artifact"]["path"] = "changed"
    assert resolved["nested"][0]["path"] == "build/output.py"

    outsider = uuid4()
    invalid = downstream.model_copy(
        update={"payload": {"x": f"${{{{ dependencies.{outsider}.result.x }}}}"}}
    )
    with pytest.raises(PayloadResolutionError, match="not a declared dependency"):
        resolve_payload(invalid, {upstream.task_id: upstream})


def test_pause_resume_cancel_and_rerun_are_durable_and_audited(tmp_path) -> None:
    store, jobs, coordinator, goal, project = _setup(tmp_path, limit=1)
    task = PlannedTask(
        project_id=project.project_id, goal_id=goal.goal_id,
        skill="rigel.skill.code_generation", payload={"value": "one"},
    )
    waiting = PlannedTask(
        project_id=project.project_id, goal_id=goal.goal_id,
        skill="rigel.skill.code_generation", payload={"value": "two"},
    )
    store.save_plan(goal.goal_id, [project], [task, waiting], 0.9, gated=False)
    coordinator.start(goal.goal_id, actor="operator")
    coordinator.pause(goal.goal_id, actor="operator", reason="maintenance")
    coordinator.pause(goal.goal_id, actor="operator", reason="duplicate")
    assert store.get_goal(goal.goal_id).status == "paused"
    assert store.get_tasks(goal.goal_id)[1].status == "pending"

    coordinator.start(goal.goal_id, actor="operator")
    first_job = jobs.get_job_by_idempotency_key(coordinator.key(goal.goal_id, task.task_id))
    _complete(jobs, first_job)
    coordinator.reconcile(goal.goal_id)
    assert store.get_tasks(goal.goal_id)[0].status == "complete"

    coordinator.rerun(goal.goal_id, task.task_id, actor="operator", reason="new input")
    rerun_job_id = store.task_execution(task.task_id)["job_id"]
    assert rerun_job_id != str(first_job.job_id)
    assert len(jobs.attempts(first_job.job_id)) == 1

    coordinator.cancel(goal.goal_id, actor="operator", reason="stop")
    coordinator.cancel(goal.goal_id, actor="operator", reason="duplicate")
    assert store.get_goal(goal.goal_id).status == "cancelled"
    assert {item.status for item in store.get_tasks(goal.goal_id)} == {"cancelled"}
    assert [event["action"] for event in store.events(goal.goal_id)] == [
        "resume", "pause", "resume", "rerun", "cancel"
    ]
