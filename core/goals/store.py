from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from datetime import timezone
from uuid import UUID

from core.contracts import GoalContract, PlannedTask, ProjectNode

_CREATE_GOALS = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id              TEXT PRIMARY KEY,
    origin               TEXT NOT NULL,
    objective            TEXT NOT NULL,
    confidence_threshold REAL NOT NULL,
    status               TEXT NOT NULL,
    plan_confidence      REAL,
    created_at           TEXT NOT NULL
)
"""

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    goal_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    ordinal     INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS planned_tasks (
    task_id         TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    goal_id         TEXT NOT NULL,
    skill           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    confidence      REAL,
    result_json     TEXT,
    error           TEXT,
    ordinal         INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS goal_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    affected_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
)
"""

_CREATE_GOAL_REPOSITORIES = """
CREATE TABLE IF NOT EXISTS goal_repositories (
    goal_id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, base_revision TEXT NOT NULL,
    base_commit_sha TEXT NOT NULL, recorded_at TEXT NOT NULL
)
"""

_UPDATABLE_TASK_FIELDS = {"status", "confidence", "result", "error"}


class GoalStore:
    def __init__(self, db_path: str | None = None):
        db_path = db_path or os.getenv("GOAL_DB_PATH", "data/goals.db")
        self.db_path = db_path
        self._lock = threading.RLock()
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        for ddl in (_CREATE_GOALS, _CREATE_PROJECTS, _CREATE_TASKS, _CREATE_EVENTS, _CREATE_GOAL_REPOSITORIES):
            self._conn.execute(ddl)
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(planned_tasks)")
        }
        if "job_id" not in columns:
            self._conn.execute("ALTER TABLE planned_tasks ADD COLUMN job_id TEXT")
        if "resolved_payload_json" not in columns:
            self._conn.execute(
                "ALTER TABLE planned_tasks ADD COLUMN resolved_payload_json TEXT"
            )
        self._conn.commit()

    def bind_repository(self, goal_id: UUID, repository_id: str, base_revision: str, base_commit_sha: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO goal_repositories VALUES (?, ?, ?, ?, ?)", (str(goal_id), repository_id, base_revision, base_commit_sha, datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

    def repository_binding(self, goal_id: UUID) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT repository_id, base_revision, base_commit_sha, recorded_at FROM goal_repositories WHERE goal_id = ?", (str(goal_id),)).fetchone()
        return dict(row) if row else None

    # ---- goals -----------------------------------------------------------
    def create_goal(self, goal: GoalContract) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO goals (goal_id, origin, objective, confidence_threshold, "
                "status, plan_confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(goal.goal_id), goal.origin, goal.objective,
                    goal.confidence_threshold, goal.status, goal.plan_confidence,
                    goal.created_at.isoformat(),
                ),
            )
            self._conn.commit()

    def get_goal(self, goal_id: UUID) -> GoalContract | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM goals WHERE goal_id = ?", (str(goal_id),))
            row = cur.fetchone()
        if row is None:
            return None
        return GoalContract(
            goal_id=UUID(row["goal_id"]),
            origin=row["origin"],
            objective=row["objective"],
            confidence_threshold=row["confidence_threshold"],
            status=row["status"],
            plan_confidence=row["plan_confidence"],
            created_at=row["created_at"],
        )

    def list_goals(self) -> list[GoalContract]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT goal_id FROM goals ORDER BY created_at DESC, rowid DESC"
            )
            ids = [r["goal_id"] for r in cur.fetchall()]
            return [self.get_goal(UUID(i)) for i in ids]

    def list_active_goals(self) -> list[GoalContract]:
        return [
            goal
            for goal in self.list_goals()
            if goal.status in ("ready", "running", "paused")
        ]

    def set_goal_status(self, goal_id: UUID, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status = ? WHERE goal_id = ?", (status, str(goal_id))
            )
            self._conn.commit()

    def try_claim(self, goal_id: UUID) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE goals SET status = 'running' "
                "WHERE goal_id = ? AND status IN ('ready', 'paused')",
                (str(goal_id),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ---- plan ----------------------------------------------------------
    def save_plan(
        self,
        goal_id: UUID,
        projects: list[ProjectNode],
        tasks: list[PlannedTask],
        plan_confidence: float,
        gated: bool,
    ) -> None:
        with self._lock:
            for i, p in enumerate(projects):
                self._conn.execute(
                    "INSERT INTO projects (project_id, goal_id, title, description, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(p.project_id), str(p.goal_id), p.title, p.description, i),
                )
            for i, t in enumerate(tasks):
                self._conn.execute(
                    "INSERT INTO planned_tasks (task_id, project_id, goal_id, skill, "
                    "payload_json, depends_on_json, status, confidence, result_json, error, ordinal) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(t.task_id), str(t.project_id), str(t.goal_id), t.skill,
                        json.dumps(t.payload), json.dumps([str(d) for d in t.depends_on]),
                        t.status, t.confidence,
                        json.dumps(t.result) if t.result is not None else None,
                        t.error, i,
                    ),
                )
            self._conn.execute(
                "UPDATE goals SET plan_confidence = ?, status = ? WHERE goal_id = ?",
                (plan_confidence, "paused" if gated else "ready", str(goal_id)),
            )
            self._conn.commit()

    # ---- tasks -------------------------------------------------------
    def _row_to_task(self, row: sqlite3.Row) -> PlannedTask:
        return PlannedTask(
            task_id=UUID(row["task_id"]),
            project_id=UUID(row["project_id"]),
            goal_id=UUID(row["goal_id"]),
            skill=row["skill"],
            payload=json.loads(row["payload_json"]),
            depends_on=[UUID(d) for d in json.loads(row["depends_on_json"])],
            status=row["status"],
            confidence=row["confidence"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
        )

    def get_tasks(self, goal_id: UUID) -> list[PlannedTask]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM planned_tasks WHERE goal_id = ? ORDER BY ordinal", (str(goal_id),)
            )
            rows = cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task(self, task_id: UUID, **fields) -> None:
        allowed = _UPDATABLE_TASK_FIELDS | {"job_id", "resolved_payload"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update task fields: {bad}")
        col_map = {
            "result": "result_json",
            "resolved_payload": "resolved_payload_json",
        }
        sets, params = [], []
        for key, value in fields.items():
            sets.append(f"{col_map.get(key, key)} = ?")
            if key in ("result", "resolved_payload"):
                params.append(json.dumps(value) if value is not None else None)
            else:
                params.append(value)
        params.append(str(task_id))
        with self._lock:
            self._conn.execute(
                f"UPDATE planned_tasks SET {', '.join(sets)} WHERE task_id = ?", params
            )
            self._conn.commit()

    def task_execution(self, task_id: UUID) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id, resolved_payload_json FROM planned_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise KeyError(str(task_id))
        return {
            "job_id": row["job_id"],
            "resolved_payload": (
                json.loads(row["resolved_payload_json"])
                if row["resolved_payload_json"]
                else None
            ),
        }

    def record_event(
        self,
        goal_id: UUID,
        *,
        actor: str,
        action: str,
        reason: str | None = None,
        affected: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO goal_events(goal_id, actor, action, reason, affected_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(goal_id), actor, action, reason,
                    json.dumps(affected or []),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def events(self, goal_id: UUID) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT actor, action, reason, affected_json, created_at FROM goal_events "
                "WHERE goal_id = ? ORDER BY event_id",
                (str(goal_id),),
            ).fetchall()
        return [
            {
                "actor": row["actor"],
                "action": row["action"],
                "reason": row["reason"],
                "affected": json.loads(row["affected_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ---- read models ----------------------------------------------
    def goal_tree(self, goal_id: UUID) -> dict:
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"no goal {goal_id}")
        tasks_by_project: dict[str, list[dict]] = {}
        for t in self.get_tasks(goal_id):
            tasks_by_project.setdefault(str(t.project_id), []).append(
                {
                    "task_id": str(t.task_id),
                    "project_id": str(t.project_id),
                    "goal_id": str(t.goal_id),
                    "skill": t.skill,
                    "payload": t.payload,
                    "depends_on": [str(d) for d in t.depends_on],
                    "status": t.status,
                    "confidence": t.confidence,
                    "result": t.result,
                    "error": t.error,
                    **self.task_execution(t.task_id),
                }
            )
        with self._lock:
            pcur = self._conn.execute(
                "SELECT * FROM projects WHERE goal_id = ? ORDER BY ordinal", (str(goal_id),)
            )
            project_rows = pcur.fetchall()
        projects = [
            {
                "project_id": pr["project_id"],
                "goal_id": pr["goal_id"],
                "title": pr["title"],
                "description": pr["description"],
                "tasks": tasks_by_project.get(pr["project_id"], []),
            }
            for pr in project_rows
        ]
        return {
            "goal": {
                "goal_id": str(goal.goal_id),
                "origin": goal.origin,
                "objective": goal.objective,
                "confidence_threshold": goal.confidence_threshold,
                "status": goal.status,
                "plan_confidence": goal.plan_confidence,
                "created_at": goal.created_at.isoformat(),
            },
            "projects": projects,
        }

    def rollup(self, goal_id: UUID) -> dict:
        tasks = self.get_tasks(goal_id)
        goal = self.get_goal(goal_id)
        confidences = [t.confidence for t in tasks if t.confidence is not None]
        return {
            "status": goal.status if goal else "unknown",
            "completed": sum(1 for t in tasks if t.status == "complete"),
            "total": len(tasks),
            "min_confidence": min(confidences) if confidences else None,
            "blocked": sum(1 for t in tasks if t.status == "blocked"),
            "failed": sum(1 for t in tasks if t.status == "failed"),
            "escalated": sum(1 for t in tasks if t.status == "escalated"),
            "cancelled": sum(1 for t in tasks if t.status == "cancelled"),
        }
