"""Append-only, hash-chained audit history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS audit_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")
        self._db.commit()

    def append(self, *, actor: str, action: str, reason: str, evidence_version: str, extra: dict | None = None) -> dict:
        prior = self._db.execute("SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
        event = {"actor": actor, "action": action, "reason": reason, "evidence_version": evidence_version, "extra": extra or {}, "prior_hash": prior[0] if prior else None}
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute("INSERT INTO audit_events(event_json,event_hash,created_at) VALUES (?,?,?)", (encoded, digest, now))
        self._db.commit()
        return {"event": event, "event_hash": digest, "created_at": now}

    def export(self) -> list[dict]:
        return [{"sequence": row[0], "event": json.loads(row[1]), "event_hash": row[2], "created_at": row[3]} for row in self._db.execute("SELECT sequence,event_json,event_hash,created_at FROM audit_events ORDER BY sequence")]

    @staticmethod
    def verify(events: list[dict]) -> bool:
        prior = None
        for item in events:
            event = item["event"]
            if event.get("prior_hash") != prior:
                return False
            digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if digest != item.get("event_hash"):
                return False
            prior = digest
        return True
