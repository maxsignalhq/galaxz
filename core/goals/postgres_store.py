"""PostgreSQL implementation of the durable goal/project store.

Schema ownership stays with ``core.storage.manage``.  This store deliberately
does not create or alter tables at runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.contracts import GoalContract, PlannedTask, ProjectNode


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class PostgresGoalStore:
    """Contract-compatible PostgreSQL persistence for goals and plans."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        if not database_url.startswith(("postgres://", "postgresql://", "postgresql+")):
            raise ValueError("PostgresGoalStore requires a PostgreSQL URL")
        self.database = database_url
        self.engine = engine or create_engine(database_url, pool_pre_ping=True, hide_parameters=True)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _goal(row) -> GoalContract:
        return GoalContract(
            goal_id=UUID(row["goal_id"]), origin=row["origin"], objective=row["objective"],
            confidence_threshold=row["confidence_threshold"], status=row["status"],
            plan_confidence=row["plan_confidence"], created_at=_timestamp(row["created_at"]),
        )

    @staticmethod
    def _task(row) -> PlannedTask:
        return PlannedTask(
            task_id=UUID(row["task_id"]), project_id=UUID(row["project_id"]),
            goal_id=UUID(row["goal_id"]), skill=row["skill"],
            payload=json.loads(row["payload_json"]),
            depends_on=[UUID(value) for value in json.loads(row["depends_on_json"])],
            status=row["status"], confidence=row["confidence"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
        )

    def create_goal(self, goal: GoalContract) -> None:
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO goals
                (goal_id, origin, objective, confidence_threshold, status, plan_confidence, created_at)
                VALUES (:id, :origin, :objective, :threshold, :status, :confidence, :created)"""), {
                "id": str(goal.goal_id), "origin": goal.origin, "objective": goal.objective,
                "threshold": goal.confidence_threshold, "status": goal.status,
                "confidence": goal.plan_confidence, "created": goal.created_at,
            })

    def get_goal(self, goal_id: UUID) -> GoalContract | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM goals WHERE goal_id=:id"), {"id": str(goal_id)}).mappings().first()
        return self._goal(row) if row else None

    def list_goals(self) -> list[GoalContract]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM goals ORDER BY created_at DESC, goal_id DESC")).mappings().all()
        return [self._goal(row) for row in rows]

    def list_active_goals(self) -> list[GoalContract]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM goals WHERE status IN ('ready','running','paused') ORDER BY created_at DESC")).mappings().all()
        return [self._goal(row) for row in rows]

    def set_goal_status(self, goal_id: UUID, status: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE goals SET status=:status WHERE goal_id=:id"), {"status": status, "id": str(goal_id)})

    def bind_repository(self, goal_id: UUID, repository_id: str, base_revision: str, base_commit_sha: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO goal_repositories
                (goal_id, repository_id, base_revision, base_commit_sha, recorded_at)
                VALUES (:goal,:repo,:revision,:sha,:recorded)
                ON CONFLICT (goal_id) DO UPDATE SET repository_id=EXCLUDED.repository_id,
                base_revision=EXCLUDED.base_revision, base_commit_sha=EXCLUDED.base_commit_sha,
                recorded_at=EXCLUDED.recorded_at"""), {
                "goal": str(goal_id), "repo": repository_id, "revision": base_revision,
                "sha": base_commit_sha, "recorded": datetime.now(timezone.utc),
            })

    def repository_binding(self, goal_id: UUID) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT repository_id,base_revision,base_commit_sha,recorded_at FROM goal_repositories WHERE goal_id=:id"), {"id": str(goal_id)}).mappings().first()
        return dict(row) if row else None

    def try_claim(self, goal_id: UUID) -> bool:
        with self.engine.begin() as c:
            result = c.execute(text("""UPDATE goals SET status='running'
                WHERE goal_id=:id AND status IN ('ready','paused')"""), {"id": str(goal_id)})
        return result.rowcount > 0

    def save_plan(self, goal_id: UUID, projects: list[ProjectNode], tasks: list[PlannedTask], plan_confidence: float, gated: bool) -> None:
        with self.engine.begin() as c:
            for ordinal, project in enumerate(projects):
                c.execute(text("""INSERT INTO projects
                    (project_id, goal_id, title, description, ordinal)
                    VALUES (:id,:goal,:title,:description,:ordinal)"""), {
                    "id": str(project.project_id), "goal": str(project.goal_id),
                    "title": project.title, "description": project.description, "ordinal": ordinal,
                })
            for ordinal, task in enumerate(tasks):
                c.execute(text("""INSERT INTO planned_tasks
                    (task_id, project_id, goal_id, skill, payload_json, depends_on_json,
                     status, confidence, result_json, error, ordinal)
                    VALUES (:id,:project,:goal,:skill,:payload,:depends,:status,:confidence,:result,:error,:ordinal)"""), {
                    "id": str(task.task_id), "project": str(task.project_id), "goal": str(task.goal_id),
                    "skill": task.skill, "payload": json.dumps(task.payload),
                    "depends": json.dumps([str(value) for value in task.depends_on]),
                    "status": task.status, "confidence": task.confidence,
                    "result": json.dumps(task.result) if task.result is not None else None,
                    "error": task.error, "ordinal": ordinal,
                })
            c.execute(text("UPDATE goals SET plan_confidence=:confidence,status=:status WHERE goal_id=:id"), {
                "confidence": plan_confidence, "status": "paused" if gated else "ready", "id": str(goal_id),
            })

    def get_tasks(self, goal_id: UUID) -> list[PlannedTask]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM planned_tasks WHERE goal_id=:id ORDER BY ordinal"), {"id": str(goal_id)}).mappings().all()
        return [self._task(row) for row in rows]

    def update_task(self, task_id: UUID, **fields) -> None:
        allowed = {"status", "confidence", "result", "error", "job_id", "resolved_payload"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update task fields: {unknown}")
        columns = {"result": "result_json", "resolved_payload": "resolved_payload_json"}
        assignments = []
        params = {"id": str(task_id)}
        for key, value in fields.items():
            column = columns.get(key, key)
            assignments.append(f"{column}=:{key}")
            params[key] = json.dumps(value) if key in columns and value is not None else value
        if assignments:
            with self.engine.begin() as c:
                c.execute(text(f"UPDATE planned_tasks SET {', '.join(assignments)} WHERE task_id=:id"), params)

    def task_execution(self, task_id: UUID) -> dict:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT job_id,resolved_payload_json FROM planned_tasks WHERE task_id=:id"), {"id": str(task_id)}).mappings().first()
        if row is None:
            raise KeyError(str(task_id))
        return {"job_id": row["job_id"], "resolved_payload": json.loads(row["resolved_payload_json"]) if row["resolved_payload_json"] else None}

    def record_event(self, goal_id: UUID, *, actor: str, action: str, reason: str | None = None, affected: list[str] | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO goal_events
                (goal_id, actor, action, reason, affected_json, created_at)
                VALUES (:goal,:actor,:action,:reason,:affected,:created)"""), {
                "goal": str(goal_id), "actor": actor, "action": action, "reason": reason,
                "affected": json.dumps(affected or []), "created": datetime.now(timezone.utc),
            })

    def events(self, goal_id: UUID) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT actor,action,reason,affected_json,created_at FROM goal_events WHERE goal_id=:id ORDER BY event_id"), {"id": str(goal_id)}).mappings().all()
        return [{"actor": row["actor"], "action": row["action"], "reason": row["reason"], "affected": json.loads(row["affected_json"]), "created_at": _timestamp(row["created_at"]).isoformat()} for row in rows]
