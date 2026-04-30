import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from orion.core.candidate_store import FinetuneCandidate, _SCHEMA_PATH, _NEW_COLUMNS


class CandidateNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"Fine-tune candidate not found: {candidate_id!r}")
        self.candidate_id = candidate_id


class CandidateClient:
    """
    Read + status-update client for candidates.db.
    Andromeda uses this — does not own the DB schema (Orion does).
    Opens a fresh connection per call; safe across threads.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if Path(db_path).exists():
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        con = sqlite3.connect(self._db_path, check_same_thread=False)
        con.execute(schema)
        for col, definition in _NEW_COLUMNS:
            try:
                con.execute(f"ALTER TABLE finetune_candidates ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass
        con.commit()
        con.close()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def list_pending(self) -> list[FinetuneCandidate]:
        if not Path(self._db_path).exists():
            return []
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT * FROM finetune_candidates WHERE status = 'pending' ORDER BY emitted_at ASC"
                ).fetchall()
            return [FinetuneCandidate(**dict(r)) for r in rows]
        except sqlite3.Error:
            return []

    def get_candidate(self, candidate_id: str) -> Optional[FinetuneCandidate]:
        if not Path(self._db_path).exists():
            return None
        try:
            with self._connect() as con:
                row = con.execute(
                    "SELECT * FROM finetune_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
            return FinetuneCandidate(**dict(row)) if row else None
        except sqlite3.Error:
            return None

    def approve(self, candidate_id: str, reviewed_by: str, reviewer_note: Optional[str]) -> None:
        existing = self.get_candidate(candidate_id)
        if existing is None:
            raise CandidateNotFoundError(candidate_id)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path, check_same_thread=False) as con:
            con.execute(
                """
                UPDATE finetune_candidates
                SET status = 'approved', reviewed_at = ?, reviewed_by = ?, reviewer_note = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now, reviewed_by, reviewer_note, candidate_id),
            )
            con.commit()

    def reject(self, candidate_id: str, reviewed_by: str, reviewer_note: Optional[str]) -> None:
        existing = self.get_candidate(candidate_id)
        if existing is None:
            raise CandidateNotFoundError(candidate_id)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path, check_same_thread=False) as con:
            con.execute(
                """
                UPDATE finetune_candidates
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?, reviewer_note = ?
                WHERE candidate_id = ? AND status = 'pending'
                """,
                (now, reviewed_by, reviewer_note, candidate_id),
            )
            con.commit()
