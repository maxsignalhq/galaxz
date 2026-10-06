from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from uuid import UUID

from core.contracts import MemoryEntry

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id      TEXT PRIMARY KEY,
    namespace      TEXT NOT NULL,
    content        TEXT NOT NULL,
    tags           TEXT NOT NULL,
    source_task_id TEXT,
    created_at     TEXT NOT NULL
)
"""
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_memories_ns ON memories (namespace, created_at)"

# Approved Orion lessons live in `skill:<skill_id>`; Andromeda always passes the newest few.
SKILL_NAMESPACE_PREFIX = "skill:"
MAX_SKILL_LESSONS = 3

# Recall ranks in Python over the most recent rows per call; bounded so a huge
# namespace cannot make every routed task slow.
_SCAN_LIMIT = 500

_STOPWORDS = frozenset(
    "the a an and or of to in on for with is are was be this that it as at by from".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) > 2 and t not in _STOPWORDS}


class NebulaStore:
    def __init__(self, db_path: str = "data/nebula.db"):
        self._lock = threading.Lock()
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            memory_id=row["memory_id"],
            namespace=row["namespace"],
            content=row["content"],
            tags=json.loads(row["tags"]),
            source_task_id=row["source_task_id"],
            created_at=row["created_at"],
        )

    def remember(
        self,
        namespace: str,
        content: str,
        tags: list[str] | None = None,
        source_task_id: UUID | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            namespace=namespace, content=content, tags=tags or [], source_task_id=source_task_id
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(entry.memory_id),
                    entry.namespace,
                    entry.content,
                    json.dumps(entry.tags),
                    str(entry.source_task_id) if entry.source_task_id else None,
                    entry.created_at.isoformat(),
                ),
            )
        return entry

    def list(self, namespace: str, limit: int = 50) -> list[MemoryEntry]:
        return self.recall([namespace], limit=limit)

    def recall(
        self, namespaces: list[str], query: str | None = None, limit: int = 5
    ) -> list[MemoryEntry]:
        if not namespaces or limit < 1:
            return []
        marks = ",".join("?" for _ in namespaces)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE namespace IN ({marks}) "
                "ORDER BY created_at DESC LIMIT ?",
                (*namespaces, _SCAN_LIMIT),
            ).fetchall()
        entries = [self._entry(r) for r in rows]  # newest first
        wanted = _tokens(query) if query else set()
        if not wanted:
            return entries[:limit]
        scored = [
            (len(wanted & _tokens(e.content + " " + " ".join(e.tags))), e) for e in entries
        ]
        # sorted() is stable, so equal scores keep newest-first order.
        ranked = sorted((p for p in scored if p[0] > 0), key=lambda p: -p[0])
        return [e for _, e in ranked[:limit]]

    def namespaces(self) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT namespace, COUNT(*) AS count FROM memories "
                "GROUP BY namespace ORDER BY count DESC, namespace"
            ).fetchall()
        return [{"namespace": r["namespace"], "count": r["count"]} for r in rows]

    def forget(self, memory_id: UUID) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE memory_id = ?", (str(memory_id),))
            return cur.rowcount > 0
