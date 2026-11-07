from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.contracts import GoalContract, PlannedTask, ProjectNode
from core.goals import DurableGoalCoordinator, GoalStore
from core.jobs import SqliteJobRepository

QUOTA = {"status": "failed", "failure_reason": "provider_quota", "confidence": 0.0}


def _setup(tmp_path, *, token_budget=None, fallback_enabled=True, tasks=2, delay=900, parallel=False):
    store = GoalStore(str(tmp_path / "goals.db"))
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    goal = GoalContract(
        origin="t", objective="x", confidence_threshold=0.65, token_budget=token_budget
    )
    project = ProjectNode(goal_id=goal.goal_id, title="p")
    store.create_goal(goal)
    planned = []
    for i in range(tasks):
        planned.append(PlannedTask(
            project_id=project.project_id, goal_id=goal.goal_id,
            skill="rigel.skill.code_generation", payload={"i": i},
            depends_on=[planned[-1].task_id] if planned and not parallel else [],
        ))
    store.save_plan(goal.goal_id, [project], planned, 0.9, gated=False)
    co = DurableGoalCoordinator(
        store, jobs, fallback_enabled=fallback_enabled, quota_resume_delay_s=delay
    )
    return store, jobs, co, goal, planned


def _finish(jobs, job_key, result):
    job = jobs.get_job_by_idempotency_key(job_key)
    claimed = jobs.claim(worker_id="w", lease_seconds=30)
    assert claimed is not None and claimed[0].job_id == job.job_id
    jobs.complete(
        job_id=job.job_id, lease_token=claimed[1].lease_token,
        output_ref=f"o:{job.job_id}", result=result,
    )


def _ok(**extra):
    return {"status": "complete", "confidence": 0.9, "result": {}, **extra}


def test_budget_exhausted_pauses_before_next_dispatch(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=100)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 120)
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "token_budget"
    assert got.resume_after is None
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is None


def test_no_budget_never_pauses(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=None)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 10**9)
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "running"
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is not None


def test_goal_completes_when_last_task_ends_over_budget(tmp_path):
    store, jobs, co, goal, (a,) = _setup(tmp_path, token_budget=10, tasks=1)
    co.start(goal.goal_id)
    store.add_tokens_used(goal.goal_id, 50)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "complete"


def test_budget_pause_not_auto_resumed_and_resume_with_same_budget_repauses(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, token_budget=100)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), _ok())
    store.add_tokens_used(goal.goal_id, 120)
    co.reconcile(goal.goal_id)
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"
    co.start(goal.goal_id)  # manual resume, budget unchanged
    assert store.get_goal(goal.goal_id).status == "paused"
    store.set_token_budget(goal.goal_id, 1000)
    co.start(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "running"
    assert jobs.get_job_by_idempotency_key(co.key(goal.goal_id, b.task_id)) is not None


def test_quota_on_primary_fails_over_once_and_redispatches(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is True
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, a.task_id)}:q1") is not None
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("failover") == 1


def test_two_in_flight_quota_failures_cause_one_failover_and_no_pause(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, parallel=True)
    co.start(goal.goal_id)
    for t in (a, b):
        _finish(jobs, co.key(goal.goal_id, t.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is True
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("failover") == 1
    for t in (a, b):
        assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, t.task_id)}:q1")


def test_quota_on_fallback_pauses_with_resume_after(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, delay=900)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    _finish(jobs, f"{co.key(goal.goal_id, a.task_id)}:q1", {**QUOTA, "model_tier": "fallback"})
    before = datetime.now(timezone.utc)
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    delta = (got.resume_after - before).total_seconds()
    assert 890 <= delta <= 910
    assert store.get_tasks(goal.goal_id)[0].status == "pending"


def test_no_fallback_configured_pauses_immediately(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, fallback_enabled=False)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert got.fallback_used is False


def test_due_quota_pause_auto_resumes_on_primary(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    _finish(jobs, f"{co.key(goal.goal_id, a.task_id)}:q1", {**QUOTA, "model_tier": "fallback"})
    co.reconcile(goal.goal_id)
    assert store.get_goal(goal.goal_id).status == "paused"

    store.pause_with_reason(
        goal.goal_id, "provider_quota", datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    co.reconcile_all()
    got = store.get_goal(goal.goal_id)
    assert got.status == "running"
    assert got.fallback_used is False and got.pause_reason is None
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, a.task_id)}:q2") is not None


def test_not_yet_due_and_review_pauses_are_left_alone(tmp_path):
    store, jobs, co, goal, _ = _setup(tmp_path)
    co.start(goal.goal_id)
    store.pause_with_reason(
        goal.goal_id, "provider_quota", datetime.now(timezone.utc) + timedelta(minutes=5)
    )
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"
    store.clear_pause(goal.goal_id)  # now a plain/review pause: pause_reason NULL
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"


def test_restart_after_failover_dispatches_exactly_once(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    # simulate a crash between "reset to pending" and "record the new job"
    store.update_task(a.task_id, status="pending", job_id=None)
    restarted = DurableGoalCoordinator(
        GoalStore(str(tmp_path / "goals.db")),
        SqliteJobRepository(tmp_path / "jobs.db"),
        fallback_enabled=True,
    )
    restarted.reconcile_all()
    keys = [
        j.idempotency_key for j in jobs.list_jobs(organization_id="default", limit=50)
        if j.idempotency_key.startswith(co.key(goal.goal_id, a.task_id))
    ]
    assert sorted(keys) == [
        co.key(goal.goal_id, a.task_id),
        f"{co.key(goal.goal_id, a.task_id)}:q1",
    ]


def test_non_quota_failure_still_fails_the_goal(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id),
            {"status": "failed", "failure_reason": "boom", "confidence": 0.0})
    co.reconcile(goal.goal_id)
    assert store.get_tasks(goal.goal_id)[0].status == "failed"
    assert store.get_goal(goal.goal_id).status == "failed"


def test_start_clears_failover_state(tmp_path):
    store, jobs, co, goal, _ = _setup(tmp_path)
    store.pause_with_reason(goal.goal_id, "provider_quota", None)
    store.set_fallback_used(goal.goal_id, True)
    co.start(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.fallback_used is False and got.pause_reason is None


def _past():
    return datetime.now(timezone.utc) - timedelta(seconds=1)


def test_rerun_clears_stale_provider_quota_pause(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    store.update_task(a.task_id, status="failed", error="boom")
    store.pause_with_reason(goal.goal_id, "provider_quota", _past())
    store.set_fallback_used(goal.goal_id, True)
    co.rerun(goal.goal_id, a.task_id, actor="t")
    got = store.get_goal(goal.goal_id)
    assert got.status == "running"
    assert got.pause_reason is None and got.resume_after is None
    assert got.fallback_used is False
    store.set_goal_status(goal.goal_id, "paused")  # e.g. an escalation / manual pause
    co.reconcile_all()
    assert store.get_goal(goal.goal_id).status == "paused"


def test_parallel_fallback_quota_results_cost_one_pause(tmp_path):
    store, jobs, co, goal, tasks = _setup(tmp_path, tasks=3, parallel=True)
    co.start(goal.goal_id)
    store.set_fallback_used(goal.goal_id, True)  # post-failover: jobs ran on the fallback
    for t in tasks:
        _finish(jobs, co.key(goal.goal_id, t.task_id), {**QUOTA, "model_tier": "fallback"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert [t.status for t in store.get_tasks(goal.goal_id)] == ["pending"] * 3
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("pause") == 1

    store.pause_with_reason(goal.goal_id, "provider_quota", _past())
    co.reconcile_all()
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is False
    for t in tasks:
        assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, t.task_id)}:q1")


def test_result_finished_before_resume_is_stale_and_does_not_failover(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, parallel=True)
    co.start(goal.goal_id)
    store.set_fallback_used(goal.goal_id, True)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "fallback"})
    co.reconcile(goal.goal_id)  # a's result pauses the goal; b still running
    assert store.get_goal(goal.goal_id).status == "paused"
    _finish(jobs, co.key(goal.goal_id, b.task_id), {**QUOTA, "model_tier": "primary"})
    store.pause_with_reason(goal.goal_id, "provider_quota", _past())
    co.reconcile_all()
    got = store.get_goal(goal.goal_id)
    assert got.status == "running" and got.fallback_used is False
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("failover") == 0
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, b.task_id)}:q1")


def test_same_quota_result_is_handled_once(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path)
    co.start(goal.goal_id)
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    stale_job_id = store.task_execution(a.task_id)["job_id"]
    task = store.get_tasks(goal.goal_id)[0]
    assert co._handle_provider_quota(goal.goal_id, task, "primary", stale_job_id, False) is False
    # a second reconciler holding the same stale view must not record or re-dispatch again
    assert co._handle_provider_quota(goal.goal_id, task, "primary", stale_job_id, False) is False
    actions = [e["action"] for e in store.events(goal.goal_id)]
    assert actions.count("provider_quota") == 1


def test_fallback_flag_without_enabled_fallback_pauses_instead_of_hot_looping(tmp_path):
    store, jobs, co, goal, (a, b) = _setup(tmp_path, fallback_enabled=False)
    co.start(goal.goal_id)
    store.set_fallback_used(goal.goal_id, True)  # persisted before the fallback was removed
    _finish(jobs, co.key(goal.goal_id, a.task_id), {**QUOTA, "model_tier": "primary"})
    co.reconcile(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert jobs.get_job_by_idempotency_key(f"{co.key(goal.goal_id, a.task_id)}:q1") is None
