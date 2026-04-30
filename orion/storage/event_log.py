import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import aiosqlite

from core.contracts import FeedbackEvent, OutcomeType, RefineryFeedbackEvent


def _derive_domain(skill_id: str, agent_id: str) -> Optional[str]:
    if agent_id == "rigel" or skill_id.startswith("rigel."):
        return "rigel"
    if agent_id == "vega" or skill_id.startswith("qa."):
        return "vega"
    return None


class EventLog:
    def __init__(self) -> None:
        self._db_path: str = ""

    async def init_db(self, db_path: str) -> None:
        self._db_path = db_path
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS feedback_events (
                    id               TEXT PRIMARY KEY,
                    task_id          TEXT NOT NULL,
                    task_category    TEXT NOT NULL,
                    agent_id         TEXT NOT NULL,
                    outcome          TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    input_hash       TEXT NOT NULL,
                    agent_output     TEXT NOT NULL,
                    human_correction TEXT,
                    latency_ms       INTEGER NOT NULL,
                    timestamp        TEXT NOT NULL,
                    quarantined      INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS quarantine_log (
                    id         TEXT PRIMARY KEY,
                    event_id   TEXT NOT NULL,
                    reason     TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (event_id) REFERENCES feedback_events(id)
                )
            """)
            # Primary events table: populated from RefineryFeedbackEvent
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id               TEXT PRIMARY KEY,
                    task_id          TEXT NOT NULL,
                    skill_id         TEXT NOT NULL,
                    agent_id         TEXT NOT NULL,
                    domain           TEXT NOT NULL,
                    outcome          TEXT NOT NULL,
                    confidence       REAL NOT NULL,
                    human_verified   INTEGER DEFAULT 0,
                    payload          TEXT,
                    result           TEXT,
                    human_correction TEXT,
                    latency_ms       INTEGER,
                    created_at       TEXT DEFAULT (datetime('now')),
                    quarantined      INTEGER DEFAULT 0,
                    exported_at      TEXT
                )
            """)
            # Tracks which events have been processed by the curation pipeline
            await db.execute("""
                CREATE TABLE IF NOT EXISTS curated_events (
                    source_event_id TEXT PRIMARY KEY,
                    curated_at      TEXT DEFAULT (datetime('now')),
                    domain          TEXT
                )
            """)
            await db.commit()

    # ------------------------------------------------------------------
    # RefineryFeedbackEvent path (new primary ingest target)
    # ------------------------------------------------------------------

    async def append_event(
        self,
        event: RefineryFeedbackEvent,
        quarantined: bool = False,
    ) -> str:
        """Write a RefineryFeedbackEvent to the events table.

        Uses task_id as the primary key — idempotent on replay.
        If Rigel retries the same task_id, only the first event sticks.
        """
        event_id = str(event.task_id)
        domain = _derive_domain(event.skill, event.agent_id) or "__unknown__"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO events
                    (id, task_id, skill_id, agent_id, domain, outcome, confidence,
                     human_verified, human_correction, latency_ms, quarantined)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    str(event.task_id),
                    event.skill,
                    event.agent_id,
                    domain,
                    event.outcome,
                    event.confidence_score,
                    1 if event.human_verified else 0,
                    event.human_correction,
                    event.latency_ms,
                    1 if quarantined else 0,
                ),
            )
            await db.commit()
        return event_id

    async def get_uncurated_events(self) -> list[dict]:
        """Return high-quality events not yet processed by the curation pipeline.

        Confidence threshold for un-verified events (>= 0.9) is intentionally
        higher than the ingest eligibility gate (>= 0.75) — only strong signals
        flow into the training dataset.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE quarantined = 0
                  AND (
                      (human_verified = 1)
                      OR (confidence >= 0.9 AND outcome = 'success')
                  )
                  AND id NOT IN (
                      SELECT source_event_id FROM curated_events
                  )
                ORDER BY created_at ASC
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def mark_curated(self, event_ids: list[str], domain: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO curated_events (source_event_id, curated_at, domain) VALUES (?, ?, ?)",
                [(eid, now, domain) for eid in event_ids],
            )
            await db.commit()

    async def get_unexported_events(self) -> list[dict]:
        """Return eligible events not yet exported to a fine-tune candidate."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE quarantined = 0 AND exported_at IS NULL
                ORDER BY created_at ASC
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def mark_exported(self, event_ids: list[str], exported_at: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                "UPDATE events SET exported_at = ? WHERE id = ?",
                [(exported_at, eid) for eid in event_ids],
            )
            await db.commit()

    async def count_events(self) -> int:
        if not self._db_path or not Path(self._db_path).exists():
            return 0
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM events WHERE quarantined = 0"
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    async def count_unexported_by_domain(self) -> dict[str, int]:
        if not self._db_path:
            return {}
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    """
                    SELECT domain, COUNT(*) FROM events
                    WHERE quarantined = 0 AND exported_at IS NULL
                    GROUP BY domain
                    """
                )
                rows = await cur.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    async def migrate_flat_jsonl(self, dataset_path: str) -> int:
        """One-time migration: read flat {skill}.jsonl files, insert into events table, delete files."""
        import re
        uuid_re = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE,
        )
        ds_path = Path(dataset_path)
        if not ds_path.exists():
            return 0

        total_migrated = 0
        for entry in sorted(ds_path.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".jsonl"):
                continue
            if uuid_re.match(entry.stem):
                continue

            rows = []
            try:
                for raw in entry.read_text(encoding="utf-8").splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    feedback_event_id = str(data.get("feedback_event_id", ""))
                    if not feedback_event_id:
                        continue

                    # TrainingExample stores the full skill name in the "domain" field
                    skill_id = str(data.get("domain", entry.stem))
                    agent_id = "rigel" if skill_id.startswith("rigel") else "vega"
                    domain = agent_id
                    confidence = float(data.get("quality_score", 0.75))
                    source = data.get("source", "")
                    human_verified = 1 if source == "human_correction" else 0
                    created_at = data.get("created_at", datetime.now(timezone.utc).isoformat())
                    exported_at = data.get("exported_at")

                    rows.append((
                        feedback_event_id,      # id (PRIMARY KEY)
                        feedback_event_id,      # task_id
                        skill_id,               # skill_id
                        agent_id,               # agent_id
                        domain,                 # domain
                        "success",              # outcome (eligible events only)
                        confidence,             # confidence
                        human_verified,         # human_verified
                        json.dumps({"prompt": data.get("prompt", "")}),       # payload
                        json.dumps({"completion": data.get("completion", "")}), # result
                        None,                   # human_correction
                        None,                   # latency_ms
                        str(created_at),        # created_at
                        0,                      # quarantined
                        exported_at,            # exported_at
                    ))
            except OSError:
                continue

            if not rows:
                continue

            async with aiosqlite.connect(self._db_path) as db:
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO events
                        (id, task_id, skill_id, agent_id, domain, outcome, confidence,
                         human_verified, payload, result, human_correction, latency_ms,
                         created_at, quarantined, exported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                await db.commit()

            migrated = len(rows)
            total_migrated += migrated
            try:
                entry.unlink()
                print(f"[migration] {entry.name}: {migrated} events migrated and file removed")
            except OSError as exc:
                print(f"[migration] {entry.name}: {migrated} events migrated but could not remove: {exc}")

        return total_migrated

    # ------------------------------------------------------------------
    # FeedbackEvent path (heuristics / review queue actions)
    # ------------------------------------------------------------------

    async def append(self, event: FeedbackEvent) -> str:
        event_id = str(uuid4())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO feedback_events
                    (id, task_id, task_category, agent_id, outcome,
                     confidence_score, input_hash, agent_output,
                     human_correction, latency_ms, timestamp, quarantined)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    event_id,
                    str(event.task_id),
                    event.task_category,
                    event.agent_id,
                    event.outcome.value,
                    event.confidence_score,
                    event.input_hash,
                    json.dumps(event.agent_output),
                    json.dumps(event.human_correction) if event.human_correction is not None else None,
                    event.latency_ms,
                    event.timestamp.isoformat(),
                ),
            )
            await db.commit()
        return event_id

    async def quarantine(self, event_id: str, reason: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE feedback_events SET quarantined = 1 WHERE id = ?",
                (event_id,),
            )
            await db.execute(
                "INSERT INTO quarantine_log (id, event_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), event_id, reason, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_window(
        self,
        task_category: str,
        hours: int = 24,
    ) -> list[FeedbackEvent]:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        cutoff = cutoff - timedelta(hours=hours)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM feedback_events
                WHERE task_category = ?
                  AND quarantined = 0
                  AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (task_category, cutoff.isoformat()),
            )
            rows = await cursor.fetchall()

        return [_row_to_event(row) for row in rows]

    async def list_domains(self) -> list[str]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT task_category FROM feedback_events WHERE quarantined = 0"
            )
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_by_agent(
        self,
        agent_id: str,
        days: int = 7,
    ) -> list[FeedbackEvent]:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM feedback_events
                WHERE agent_id = ?
                  AND quarantined = 0
                  AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (agent_id, cutoff.isoformat()),
            )
            rows = await cursor.fetchall()

        return [_row_to_event(row) for row in rows]


def _row_to_event(row: aiosqlite.Row) -> FeedbackEvent:
    return FeedbackEvent(
        task_id=row["task_id"],
        task_category=row["task_category"],
        agent_id=row["agent_id"],
        outcome=OutcomeType(row["outcome"]),
        confidence_score=row["confidence_score"],
        input_hash=row["input_hash"],
        agent_output=json.loads(row["agent_output"]),
        human_correction=json.loads(row["human_correction"]) if row["human_correction"] else None,
        latency_ms=row["latency_ms"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )
