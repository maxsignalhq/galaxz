"""Single-use approvals for tasks held by a `require_review` policy rule."""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_TTL_S = 3600

_CREATE = """
CREATE TABLE IF NOT EXISTS policy_grants (
    grant_id    TEXT PRIMARY KEY,
    origin      TEXT NOT NULL,
    skill       TEXT NOT NULL,
    digest      TEXT NOT NULL,
    granted_by  TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT
)
"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_policy_grants_key ON policy_grants (origin, skill, digest)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GrantStore:
    """SQLite store, opened lazily so deployments without policy never create the file."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            path = self._db_path or os.getenv("POLICY_DB_PATH", "data/policy.db")
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute(_CREATE)
            self._conn.execute(_INDEX)
            self._conn.commit()
        return self._conn

    def issue(
        self,
        *,
        origin: str,
        skill: str,
        digest: str,
        ttl_s: int = DEFAULT_TTL_S,
        granted_by: str | None = None,
    ) -> str:
        grant_id = str(uuid.uuid4())
        now = _now()
        with self._lock:
            conn = self._connection()
            conn.execute(
                "INSERT INTO policy_grants(grant_id, origin, skill, digest, granted_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (grant_id, origin, skill, digest, granted_by, now.isoformat(), (now + timedelta(seconds=ttl_s)).isoformat()),
            )
            conn.commit()
        return grant_id

    def consume(self, *, origin: str, skill: str, digest: str) -> bool:
        """Atomically use one unexpired grant; False when there is none."""
        now = _now().isoformat()
        with self._lock:
            conn = self._connection()
            cur = conn.execute(
                "UPDATE policy_grants SET consumed_at = ? WHERE grant_id = ("
                "  SELECT grant_id FROM policy_grants "
                "  WHERE origin = ? AND skill = ? AND digest = ? AND consumed_at IS NULL AND expires_at > ? "
                "  ORDER BY created_at LIMIT 1)",
                (now, origin, skill, digest, now),
            )
            conn.commit()
        return cur.rowcount > 0
