from __future__ import annotations

import logging
import threading
from uuid import UUID

from core.contracts import TaskContract

logger = logging.getLogger(__name__)


class GoalRunner:
    def __init__(self, andromeda, store):
        self._andromeda = andromeda
        self._store = store

    def run_async(self, goal_id: UUID) -> threading.Thread:
        thread = threading.Thread(
            target=self.run, args=(goal_id,), name=f"goal-{goal_id}", daemon=True
        )
        thread.start()
        return thread

    def run(self, goal_id: UUID) -> None:
        if not self._store.try_claim(goal_id):
            logger.info("goal %s already running or not runnable - skipping", goal_id)
            return
        try:
            self._drive(goal_id)
        except Exception:
            logger.exception("goal %s runner crashed", goal_id)
            self._store.set_goal_status(goal_id, "failed")

    def _drive(self, goal_id: UUID) -> None:
        goal = self._store.get_goal(goal_id)
        threshold = goal.confidence_threshold

        while True:
            tasks = self._store.get_tasks(goal_id)
            by_id = {t.task_id: t for t in tasks}
            pending = [t for t in tasks if t.status == "pending"]
            if not pending:
                self._store.set_goal_status(goal_id, "complete")
                return

            ready = [
                t for t in pending
                if all(by_id[d].status == "complete" for d in t.depends_on)
            ]
            if not ready:
                # An upstream dependency failed or escalated. The branch that
                # stopped us already set paused/failed; this is a safety net.
                self._store.set_goal_status(goal_id, "paused")
                return

            task = ready[0]
            self._store.update_task(task.task_id, status="running")
            contract = TaskContract(
                origin=f"goal:{goal_id}",
                skill=task.skill,
                payload=task.payload,
                confidence_threshold=threshold,
            )
            result = self._andromeda.route(task=contract)
            status = result.get("status")
            confidence = result.get("confidence")
            task_result = result.get("result") if isinstance(result.get("result"), dict) else None

            if status == "complete" and (confidence or 0.0) >= threshold:
                self._store.update_task(
                    task.task_id, status="complete", confidence=confidence, result=task_result,
                )
                continue

            if status in ("failed", "no_agent_found"):
                self._store.update_task(
                    task.task_id, status="failed", confidence=confidence,
                    error=result.get("failure_reason") or status,
                )
                self._store.set_goal_status(goal_id, "failed")
                return

            # escalated, sub-threshold complete, or review_pending
            self._store.update_task(
                task.task_id, status="escalated", confidence=confidence, result=task_result,
            )
            self._andromeda.review_queue.enqueue(
                task_id=str(task.task_id),
                task_type=task.skill,
                confidence=confidence or 0.0,
                payload=task.payload,
                skill_id=task.skill,
                agent_output=task_result or {},
                goal_id=str(goal_id),
            )
            self._store.set_goal_status(goal_id, "paused")
            return

    def resolve_escalated_task(self, goal_id: UUID, task_id: UUID, approved: bool):
        """Update the reviewed task, then continue the DAG off the request thread.

        Returns the runner thread (approved path) or None (rejected path) so
        callers/tests can join; the HTTP handler ignores it.
        """
        if approved:
            self._store.update_task(task_id, status="complete")
            return self.run_async(goal_id)
        self._store.update_task(task_id, status="failed", error="rejected by reviewer")
        self._store.set_goal_status(goal_id, "failed")
        return None
