from __future__ import annotations

import logging
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from agents.andromeda.review_queue import ReviewQueue
from core.artifacts.store import ArtifactStore

from .repository import SqliteJobRepository

logger = logging.getLogger(__name__)


class CompletionPublisher:
    """Replay committed outputs into idempotent artifact and review stores."""

    def __init__(
        self,
        jobs: SqliteJobRepository,
        artifacts: ArtifactStore,
        reviews: ReviewQueue,
    ) -> None:
        self.jobs = jobs
        self.artifacts = artifacts
        self.reviews = reviews

    def publish_pending(self) -> None:
        for event in self.jobs.pending_completions():
            try:
                self._publish(event)
            except Exception:
                # The committed result remains authoritative. Retry publication,
                # never re-execute the agent because a downstream store failed.
                logger.exception("completion_publication_failed", extra=event)

    def _publish(self, event: dict) -> None:
        job_id = UUID(event["job_id"])
        task = self.jobs.get_task(job_id)
        result = self.jobs.get_result(job_id)
        if task is None or result is None:
            raise RuntimeError("committed completion is missing its task or result")
        versions = self.artifacts.record(
            result.get("artifacts") or [],
            workspace_root=task.workspace_root or "",
            task_id=str(task.task_id),
            skill=task.skill,
            attempt_id=event["attempt_id"],
        )
        references = []
        for version in versions:
            row = self.artifacts.get_version(version["identity_key"], version["version"])
            if row is None:
                raise RuntimeError("artifact publication did not persist its content")
            references.append({
                "identity_key": version["identity_key"],
                "version": version["version"],
                "content_hash": row["content_hash"],
            })
        if result.get("status") == "escalated":
            goal_id = task.origin.removeprefix("goal:") if task.origin.startswith("goal:") else None
            output = result.get("result") if isinstance(result.get("result"), dict) else {}
            self.reviews.enqueue(
                task_id=event["attempt_id"] if goal_id else str(task.task_id),
                task_type=result.get("task_type") or task.skill.split(".")[-1],
                confidence=result.get("confidence") or 0.0,
                payload=task.payload,
                skill_id=task.skill,
                agent_id=result.get("assigned_agent") or "",
                agent_output={**output, "artifact_versions": references},
                sla_deadline=(datetime.fromisoformat(event["created_at"]) + timedelta(hours=1)).isoformat(),
                goal_id=goal_id,
                planned_task_id=str(task.task_id) if goal_id else None,
                attempt_id=event["attempt_id"],
            )
            review = self.reviews.get_by_task_id(event["attempt_id"] if goal_id else str(task.task_id))
            if review is None or review["attempt_id"] != event["attempt_id"] or (
                review["agent_output"] != {**output, "artifact_versions": references}
            ):
                raise RuntimeError("review identity already belongs to different completion evidence")
        self.jobs.acknowledge_completion(job_id)
