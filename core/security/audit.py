"""Append-only, hash-chained audit history."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _digest(event: dict) -> str:
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: appends manage their own BEGIN IMMEDIATE transaction so that
        # threads and separate processes serialise instead of forking the chain.
        self._db = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._db.execute("CREATE TABLE IF NOT EXISTS audit_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")

    def append(self, *, actor: str, action: str, reason: str, evidence_version: str = "audit-v1", extra: dict | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                prior = self._db.execute("SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
                event = {"actor": actor, "action": action, "reason": reason, "evidence_version": evidence_version, "extra": extra or {}, "prior_hash": prior[0] if prior else None}
                encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(encoded.encode()).hexdigest()
                self._db.execute("INSERT INTO audit_events(event_json,event_hash,created_at) VALUES (?,?,?)", (encoded, digest, now))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return {"event": event, "event_hash": digest, "created_at": now}

    def export(self, after: int = 0, limit: int | None = None) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT sequence,event_json,event_hash,created_at FROM audit_events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (after, -1 if limit is None else limit),
            ).fetchall()
        return [{"sequence": row[0], "event": json.loads(row[1]), "event_hash": row[2], "created_at": row[3]} for row in rows]

    def verify_chain(self) -> dict:
        """Walk the whole stored chain; report the first sequence at which it breaks."""
        prior = None
        count = 0
        with self._lock:
            for sequence, event_json, event_hash in self._db.execute("SELECT sequence,event_json,event_hash FROM audit_events ORDER BY sequence"):
                event = json.loads(event_json)
                if event.get("prior_hash") != prior or _digest(event) != event_hash:
                    return {"valid": False, "events": count, "head": prior, "broken_at": sequence}
                prior = event_hash
                count += 1
        return {"valid": True, "events": count, "head": prior, "broken_at": None}

    @staticmethod
    def verify(events: list[dict]) -> bool:
        prior = None
        for item in events:
            event = item["event"]
            if event.get("prior_hash") != prior:
                return False
            if _digest(event) != item.get("event_hash"):
                return False
            prior = _digest(event)
        return True


_logs: dict[str, AuditLog] = {}
_logs_lock = threading.Lock()


def default_audit_log() -> AuditLog:
    path = os.getenv("GALAXZ_AUDIT_DB", "data/audit.db")
    with _logs_lock:
        if path not in _logs:
            _logs[path] = AuditLog(path)
        return _logs[path]


def audit_event(actor: str, action: str, reason: str, **extra) -> None:
    """Record an event in the default log. Best effort: an audit outage never breaks the caller."""
    try:
        default_audit_log().append(actor=actor, action=action, reason=reason, extra=extra)
    except Exception:
        logger.error("audit write failed for action=%s", action, exc_info=True)
