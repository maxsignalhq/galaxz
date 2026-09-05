from __future__ import annotations

import os
from uuid import UUID

from core.contracts import JobStatus
from core.contracts import TaskContract
from core.jobs import SqliteJobRepository

from .store import GoalStore
from .substitution import PayloadResolutionError
from .substitution import resolve_payload


class DurableGoalCoordinator:
    def __init__(
        self,
        store: GoalStore,
        jobs: SqliteJobRepository,
        *,
        review_queue=None,
        per_goal_limit: int | None = None,
        global_limit: int | None = None,
    ) -> None:
        self.store = store
        self.jobs = jobs
        self.review_queue = review_queue
        self.per_goal_limit = per_goal_limit or int(os.getenv("GOAL_CONCURRENCY", "4"))
        self.global_limit = global_limit or int(os.getenv("GLOBAL_JOB_CONCURRENCY", "32"))

    @staticmethod
    def key(goal_id: UUID, task_id: UUID) -> str:
        return f"goal:{goal_id}:task:{task_id}"

    def reconcile_all(self) -> None:
        for goal in self.store.list_active_goals():
            if goal.status != "paused":
                self.reconcile(goal.goal_id)

    def start(self, goal_id: UUID, *, actor: str = "system") -> None:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise KeyError(str(goal_id))
        if goal.status not in ("ready", "paused", "running"):
            raise ValueError(f"goal is {goal.status}, cannot start")
        self.store.set_goal_status(goal_id, "running")
        self.store.record_event(goal_id, actor=actor, action="resume")
        self.reconcile(goal_id)

    def reconcile(self, goal_id: UUID) -> None:
        goal = self.store.get_goal(goal_id)
        if goal is None or goal.status != "running":
            return
        tasks = self.store.get_tasks(goal_id)
        by_id = {task.task_id: task for task in tasks}

        for task in tasks:
            if task.status != "running":
                continue
            execution = self.store.task_execution(task.task_id)
            job = (
                self.jobs.get_job(UUID(execution["job_id"]))
                if execution["job_id"]
                else self.jobs.get_job_by_idempotency_key(self.key(goal_id, task.task_id))
            )
            if job is None:
                self.store.update_task(task.task_id, status="pending", job_id=None)
            elif job.status is JobStatus.completed:
                result = self.jobs.get_result(job.job_id) or {}
                confidence = result.get("confidence")
                state = result.get("status")
                task_result = result.get("result") if isinstance(result.get("result"), dict) else result
                if state == "complete" and (confidence or 0.0) >= goal.confidence_threshold:
                    self.store.update_task(
                        task.task_id, status="complete", confidence=confidence, result=task_result
                    )
                elif state in ("failed", "no_agent_found"):
                    self.store.update_task(
                        task.task_id, status="failed", confidence=confidence,
                        error=result.get("failure_reason") or state,
                    )
                else:
                    self.store.update_task(
                        task.task_id, status="escalated", confidence=confidence, result=task_result
                    )
                    self.store.set_goal_status(goal_id, "paused")
                    return
            elif job.status in (JobStatus.failed, JobStatus.cancelled):
                self.store.update_task(task.task_id, status="failed", error=job.status.value)

        tasks = self.store.get_tasks(goal_id)
        by_id = {task.task_id: task for task in tasks}
        failed_ids = {task.task_id for task in tasks if task.status in ("failed", "blocked", "cancelled")}
        changed = True
        while changed:
            changed = False
            for task in tasks:
                if (
                    task.status == "pending"
                    and task.task_id not in failed_ids
                    and any(dep in failed_ids for dep in task.depends_on)
                ):
                    self.store.update_task(task.task_id, status="blocked", error="dependency failed")
                    failed_ids.add(task.task_id)
                    changed = True

        tasks = self.store.get_tasks(goal_id)
        running = sum(task.status == "running" for task in tasks)
        global_running = sum(job.status is JobStatus.running for job in self.jobs.list_jobs(limit=500))
        slots = min(self.per_goal_limit - running, self.global_limit - global_running)
        for task in tasks:
            if slots <= 0:
                break
            if task.status != "pending":
                continue
            if not all(by_id[dep].status == "complete" for dep in task.depends_on):
                continue
            try:
                payload = resolve_payload(task, by_id)
            except PayloadResolutionError as exc:
                self.store.update_task(task.task_id, status="failed", error=str(exc))
                continue
            contract = TaskContract(
                task_id=task.task_id,
                origin=f"goal:{goal_id}",
                skill=task.skill,
                payload=payload,
                confidence_threshold=goal.confidence_threshold,
            )
            job = self.jobs.enqueue(
                task_id=contract.task_id,
                task=contract,
                idempotency_key=self.key(goal_id, task.task_id),
            )
            self.store.update_task(
                task.task_id, status="running", job_id=str(job.job_id), resolved_payload=payload
            )
            slots -= 1

        tasks = self.store.get_tasks(goal_id)
        statuses = {task.status for task in tasks}
        if statuses <= {"complete"}:
            self.store.set_goal_status(goal_id, "complete")
            self.store.record_event(goal_id, actor="system", action="complete")
        elif not statuses.intersection({"pending", "running"}):
            self.store.set_goal_status(goal_id, "failed")

    def pause(self, goal_id: UUID, *, actor: str, reason: str | None = None) -> None:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise KeyError(str(goal_id))
        if goal.status == "paused":
            return
        if goal.status != "running":
            raise ValueError(f"goal is {goal.status}, cannot pause")
        self.store.set_goal_status(goal_id, "paused")
        self.store.record_event(goal_id, actor=actor, action="pause", reason=reason)

    def cancel(self, goal_id: UUID, *, actor: str, reason: str | None = None) -> None:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise KeyError(str(goal_id))
        if goal.status == "cancelled":
            return
        if goal.status in ("complete", "failed"):
            raise ValueError(f"goal is {goal.status}, cannot cancel")
        affected: list[str] = []
        for task in self.store.get_tasks(goal_id):
            if task.status == "running":
                execution = self.store.task_execution(task.task_id)
                if execution["job_id"]:
                    job = self.jobs.get_job(UUID(execution["job_id"]))
                    if job is not None and job.status in (JobStatus.queued, JobStatus.running):
                        self.jobs.cancel(job_id=job.job_id)
                self.store.update_task(task.task_id, status="cancelled")
                affected.append(str(task.task_id))
            elif task.status == "pending":
                self.store.update_task(task.task_id, status="cancelled")
                affected.append(str(task.task_id))
        self.store.set_goal_status(goal_id, "cancelled")
        self.store.record_event(
            goal_id, actor=actor, action="cancel", reason=reason, affected=affected
        )

    def rerun(
        self,
        goal_id: UUID,
        task_id: UUID,
        *,
        actor: str,
        reason: str | None = None,
    ) -> None:
        tasks = self.store.get_tasks(goal_id)
        by_id = {task.task_id: task for task in tasks}
        task = by_id.get(task_id)
        if task is None:
            raise KeyError(str(task_id))
        if task.status not in ("failed", "escalated", "complete"):
            raise ValueError(f"task is {task.status}, cannot rerun")
        run_number = 1 + sum(
            event["action"] == "rerun" and str(task_id) in event["affected"]
            for event in self.store.events(goal_id)
        )
        payload = resolve_payload(task, by_id)
        contract = TaskContract(
            task_id=task.task_id,
            origin=f"goal:{goal_id}",
            skill=task.skill,
            payload=payload,
            confidence_threshold=self.store.get_goal(goal_id).confidence_threshold,
        )
        job = self.jobs.enqueue(
            task_id=task.task_id,
            task=contract,
            idempotency_key=f"{self.key(goal_id, task_id)}:rerun:{run_number}",
        )
        self.store.update_task(
            task_id, status="running", error=None, result=None,
            confidence=None, job_id=str(job.job_id), resolved_payload=payload,
        )
        self.store.set_goal_status(goal_id, "running")
        self.store.record_event(
            goal_id, actor=actor, action="rerun", reason=reason,
            affected=[str(task_id)],
        )
