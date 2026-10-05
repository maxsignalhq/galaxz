"""Pending / approved / rejected skill lessons proposed by Orion (human-gated)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel

MAX_LESSON_CHARS = 300

_CREATE_CANDIDATES = """
CREATE TABLE IF NOT EXISTS lesson_candidates (
    candidate_id  TEXT PRIMARY KEY,
    skill_id      TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    content       TEXT NOT NULL,
    evidence      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    reviewed_at   TEXT,
    reviewed_by   TEXT,
    reviewer_note TEXT,
    memory_id     TEXT
)
"""
_CREATE_SOURCES = "CREATE TABLE IF NOT EXISTS lesson_sources (event_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL)"


class LessonCandidate(BaseModel):
    candidate_id: str
    skill_id: str
    agent_id: str
    content: str
    evidence: list[str]
    status: str = "pending"
    created_at: str
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewer_note: Optional[str] = None
    memory_id: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(content: str) -> str:
    return " ".join(content.split())


class LessonStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_CANDIDATES)
            conn.execute(_CREATE_SOURCES)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _candidate(row: sqlite3.Row) -> LessonCandidate:
        data = dict(row)
        data["evidence"] = json.loads(data["evidence"])
        return LessonCandidate(**data)

    def add(self, skill_id: str, agent_id: str, content: str, evidence: list[str]) -> LessonCandidate:
        candidate = LessonCandidate(
            candidate_id=str(uuid4()),
            skill_id=skill_id,
            agent_id=agent_id,
            content=normalize(content),
            evidence=list(evidence),
            created_at=_now(),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO lesson_candidates (candidate_id, skill_id, agent_id, content, evidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (
                    candidate.candidate_id, skill_id, agent_id, candidate.content,
                    json.dumps(candidate.evidence), candidate.created_at,
                ),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO lesson_sources (event_id, candidate_id) VALUES (?, ?)",
                [(event_id, candidate.candidate_id) for event_id in evidence],
            )
        return candidate

    def used_event_ids(self) -> set[str]:
        with self._lock, self._connect() as conn:
            return {row[0] for row in conn.execute("SELECT event_id FROM lesson_sources")}

    def mark_used(self, event_ids: list[str], candidate_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO lesson_sources (event_id, candidate_id) VALUES (?, ?)",
                [(event_id, candidate_id) for event_id in event_ids],
            )

    def has_content(self, skill_id: str, content: str) -> bool:
        """True when this lesson is already pending or approved for the skill."""
        wanted = normalize(content).lower()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT content FROM lesson_candidates WHERE skill_id = ? AND status IN ('pending', 'approved')",
                (skill_id,),
            ).fetchall()
        return any(normalize(r["content"]).lower() == wanted for r in rows)

    def get(self, candidate_id: str) -> Optional[LessonCandidate]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM lesson_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
        return self._candidate(row) if row else None

    def list(self, status: str | None = "pending") -> list[LessonCandidate]:
        query = "SELECT * FROM lesson_candidates"
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query + " ORDER BY created_at ASC, candidate_id ASC", params).fetchall()
        return [self._candidate(r) for r in rows]

    def claim(
        self,
        candidate_id: str,
        status: str,
        reviewed_by: str,
        reviewer_note: str | None = None,
        content: str | None = None,
    ) -> bool:
        """Atomically move pending -> approved/rejected; False if it was not pending."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE lesson_candidates SET status = ?, reviewed_at = ?, reviewed_by = ?, reviewer_note = ?, "
                "content = COALESCE(?, content) WHERE candidate_id = ? AND status = 'pending'",
                (status, _now(), reviewed_by, reviewer_note, normalize(content) if content else None, candidate_id),
            )
            return cur.rowcount > 0

    def attach_memory(self, candidate_id: str, memory_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE lesson_candidates SET memory_id = ? WHERE candidate_id = ?", (memory_id, candidate_id))

    def revert(self, candidate_id: str) -> None:
        """Put a claimed candidate back to pending (the Nebula write failed)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE lesson_candidates SET status = 'pending', reviewed_at = NULL, reviewed_by = NULL, "
                "reviewer_note = NULL, memory_id = NULL WHERE candidate_id = ?",
                (candidate_id,),
            )
