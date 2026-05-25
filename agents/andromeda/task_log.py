import json
import os
import sqlite3
import threading
from typing import Optional

from agents.andromeda.state import AndromedaState

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id           TEXT,
    task_type         TEXT,
    assigned_agent    TEXT,
    status            TEXT,
    confidence        REAL,
    retry_count       INTEGER,
    escalated_to_human INTEGER,
    failure_reason    TEXT,
    issued_at         TEXT,
    completed_at      TEXT,
    payload_json      TEXT,
    result_json       TEXT,
    PRIMARY KEY (task_id, status)
)
"""

_UPSERT = """
INSERT INTO tasks (
    task_id, task_type, assigned_agent, status, confidence,
    retry_count, escalated_to_human, failure_reason,
    issued_at, completed_at, payload_json, result_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(task_id, status) DO UPDATE SET
    task_type          = excluded.task_type,
    assigned_agent     = excluded.assigned_agent,
    confidence         = excluded.confidence,
    retry_count        = excluded.retry_count,
    escalated_to_human = excluded.escalated_to_human,
    failure_reason     = excluded.failure_reason,
    issued_at          = excluded.issued_at,
    completed_at       = excluded.completed_at,
    payload_json       = excluded.payload_json,
    result_json        = excluded.result_json
"""

_COLUMNS = [
    "task_id", "task_type", "assigned_agent", "status", "confidence",
    "retry_count", "escalated_to_human", "failure_reason",
    "issued_at", "completed_at", "payload_json", "result_json",
]


def _row_to_dict(row: tuple) -> dict:
    return dict(zip(_COLUMNS, row))


class TaskLog:
    """
    Persistent log of all tasks Andromeda processes.
    DB path defaults to 'data/andromeda_tasks.db'.
    Thread-safe. Orion will query this directly.
    """

    def __init__(self, db_path: str = "data/andromeda_tasks.db"):
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._migrate_schema()
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cur = self._conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1]: row for row in cur.fetchall()}
        if not cols:
            return
        # Old schema: task_id was sole PK (pk=1), status was not part of PK (pk=0)
        if cols.get("task_id", (0,) * 6)[5] == 1 and cols.get("status", (0,) * 6)[5] == 0:
            self._conn.execute("ALTER TABLE tasks RENAME TO _tasks_v1")
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute("INSERT INTO tasks SELECT * FROM _tasks_v1")
            self._conn.execute("DROP TABLE _tasks_v1")
            self._conn.commit()

    def write(self, state: AndromedaState) -> None:
        payload = state.model_dump(mode="python")
        payload_json = json.dumps(payload.get("payload", {}))
        result_json = json.dumps(payload.get("result") or {})
        row = (
            payload["task_id"],
            payload.get("task_type"),
            payload.get("assigned_agent"),
            payload.get("status"),
            payload.get("confidence"),
            payload.get("retry_count", 0),
            1 if payload.get("escalated_to_human") else 0,
            payload.get("failure_reason"),
            payload.get("issued_at"),
            payload.get("completed_at"),
            payload_json,
            result_json,
        )
        with self._lock:
            self._conn.execute(_UPSERT, row)
            self._conn.commit()

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM tasks WHERE task_id = ? ORDER BY rowid DESC LIMIT 1",
                (task_id,),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row is not None else None

    def update_status(self, task_id: str, task_type: str, new_status: str) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        row = (
            task_id, task_type, None, new_status, None,
            0, 0, None, None, now, "{}", "{}",
        )
        with self._lock:
            self._conn.execute(_UPSERT, row)
            self._conn.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM tasks ORDER BY issued_at DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def throughput(self, hours: int = 24) -> list[dict]:
        """Return per-hour task counts for the last `hours` hours, newest-last."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT
                    strftime('%Y-%m-%dT%H:00', issued_at) AS bucket,
                    COUNT(*) AS count
                FROM tasks
                WHERE issued_at >= datetime('now', ? || ' hours')
                  AND status IN ('complete', 'failed', 'escalated')
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (f"-{hours}",),
            )
            rows = cur.fetchall()
        return [{"bucket": r[0], "count": r[1]} for r in rows]

    def stats(self) -> dict:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'complete'  THEN 1 ELSE 0 END) AS complete,
                    SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status = 'escalated' THEN 1 ELSE 0 END) AS escalated
                FROM tasks
                """
            )
            row = cur.fetchone()
        return {
            "total": row[0],
            "complete": row[1] or 0,
            "failed": row[2] or 0,
            "escalated": row[3] or 0,
        }
