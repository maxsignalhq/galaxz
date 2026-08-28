import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS review_queue (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT    UNIQUE NOT NULL,
    task_type      TEXT,
    skill_id       TEXT    NOT NULL DEFAULT '',
    agent_id       TEXT    NOT NULL DEFAULT '',
    agent_output   TEXT    NOT NULL DEFAULT '{}',
    sla_deadline   TEXT,
    confidence     REAL,
    payload        TEXT,
    status         TEXT    NOT NULL DEFAULT 'pending',
    created_at     TEXT    NOT NULL,
    reviewed_at    TEXT,
    reviewer_notes TEXT,
    goal_id        TEXT
)
"""

_MIGRATE_STMTS = [
    "ALTER TABLE review_queue ADD COLUMN skill_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_queue ADD COLUMN agent_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_queue ADD COLUMN agent_output TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE review_queue ADD COLUMN sla_deadline TEXT",
    "ALTER TABLE review_queue ADD COLUMN goal_id TEXT",
]

_COLUMNS = [
    "id", "task_id", "task_type", "skill_id", "agent_id", "agent_output",
    "sla_deadline", "confidence", "payload", "status", "created_at",
    "reviewed_at", "reviewer_notes", "goal_id",
]


def _row_to_dict(row: tuple) -> dict:
    d = dict(zip(_COLUMNS, row))
    for field in ("payload", "agent_output"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


class ReviewQueue:
    def __init__(self, db_path: str = "data/andromeda_tasks.db"):
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        for stmt in _MIGRATE_STMTS:
            try:
                self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    def enqueue(
        self,
        task_id: str,
        task_type: str,
        confidence: float,
        payload: dict,
        skill_id: str = "",
        agent_id: str = "",
        agent_output: Optional[dict] = None,
        sla_deadline: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO review_queue
                    (task_id, task_type, skill_id, agent_id, agent_output, sla_deadline,
                     confidence, payload, status, created_at, goal_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    task_id, task_type, skill_id, agent_id,
                    json.dumps(agent_output or {}), sla_deadline,
                    confidence, json.dumps(payload), now, goal_id,
                ),
            )
            self._conn.commit()

    def get_pending(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM review_queue "
                "WHERE status = 'pending' "
                "ORDER BY COALESCE(sla_deadline, '9999') ASC, created_at ASC"
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_by_task_id(self, task_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM review_queue WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def resolve(self, task_id: str, new_status: str, reviewer_notes: Optional[str] = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE review_queue SET status = ?, reviewed_at = ?, reviewer_notes = ? "
                "WHERE task_id = ? AND status = 'pending'",
                (new_status, now, reviewer_notes, task_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def get_stats(self) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "SELECT status, COUNT(*) FROM review_queue GROUP BY status"
            )
            counts = {row[0]: row[1] for row in cur.fetchall()}

            oldest_cur = self._conn.execute(
                "SELECT created_at FROM review_queue "
                "WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
            oldest_row = oldest_cur.fetchone()

            now_iso = datetime.now(timezone.utc).isoformat()
            sla_cur = self._conn.execute(
                "SELECT COUNT(*) FROM review_queue "
                "WHERE status = 'pending' AND sla_deadline IS NOT NULL AND sla_deadline < ?",
                (now_iso,),
            )
            sla_breached = sla_cur.fetchone()[0] or 0

        oldest_age_minutes: Optional[int] = None
        if oldest_row:
            try:
                oldest_dt = datetime.fromisoformat(oldest_row[0])
                if oldest_dt.tzinfo is None:
                    oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - oldest_dt
                oldest_age_minutes = int(delta.total_seconds() / 60)
            except (ValueError, TypeError):
                pass

        return {
            "pending":  counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "accepted": counts.get("accepted", 0),
            "rejected": counts.get("rejected", 0),
            "oldest_pending_age_minutes": oldest_age_minutes,
            "sla_breached": sla_breached,
        }
