import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel

_SCHEMA_PATH = Path(__file__).parent.parent / "data" / "schema_candidates.sql"

_NEW_COLUMNS = [
    ("status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("reviewed_at", "TEXT"),
    ("reviewed_by", "TEXT"),
    ("reviewer_note", "TEXT"),
]


class FinetuneCandidate(BaseModel):
    candidate_id: str
    agent_id: str
    example_count: int
    quality_avg: float
    emitted_at: str
    status: str = "pending"
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewer_note: Optional[str] = None


class CandidateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        con = sqlite3.connect(db_path, check_same_thread=False)
        con.execute(schema)
        # Idempotently add columns that may be absent from older DBs
        for col, definition in _NEW_COLUMNS:
            try:
                con.execute(f"ALTER TABLE finetune_candidates ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass
        con.commit()
        con.close()

    def has_candidate(self, agent_id: str) -> bool:
        con = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            row = con.execute(
                "SELECT 1 FROM finetune_candidates WHERE agent_id = ? LIMIT 1",
                (agent_id,),
            ).fetchone()
            return row is not None
        finally:
            con.close()

    def add(self, agent_id: str, example_count: int, quality_avg: float) -> FinetuneCandidate:
        candidate = FinetuneCandidate(
            candidate_id=str(uuid4()),
            agent_id=agent_id,
            example_count=example_count,
            quality_avg=quality_avg,
            emitted_at=datetime.now(timezone.utc).isoformat(),
        )
        con = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            con.execute(
                """
                INSERT INTO finetune_candidates
                    (candidate_id, agent_id, example_count, quality_avg, emitted_at, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    candidate.candidate_id,
                    candidate.agent_id,
                    candidate.example_count,
                    candidate.quality_avg,
                    candidate.emitted_at,
                ),
            )
            con.commit()
        finally:
            con.close()
        return candidate

    def get(self, agent_id: str) -> FinetuneCandidate | None:
        con = sqlite3.connect(self._db_path, check_same_thread=False)
        try:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM finetune_candidates WHERE agent_id = ? LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None
            return FinetuneCandidate(**dict(row))
        finally:
            con.close()
