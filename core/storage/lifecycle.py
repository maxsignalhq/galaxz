"""Operational-data lifecycle controls for local Galaxz deployments."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

DEFAULT_RETENTION_DAYS = {"jobs": 90, "tasks": 90, "goals": 365, "reviews": 365, "artifacts": 365}


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention windows in days, keyed by operational data category."""

    days: Mapping[str, int]

    def __post_init__(self) -> None:
        unknown = set(self.days) - set(DEFAULT_RETENTION_DAYS)
        if unknown:
            raise ValueError(f"unknown retention categories: {', '.join(sorted(unknown))}")
        if any(not isinstance(value, int) or value < 0 for value in self.days.values()):
            raise ValueError("retention periods must be non-negative integer day counts")

    @classmethod
    def from_file(cls, path: str | Path) -> "RetentionPolicy":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls({**DEFAULT_RETENTION_DAYS, **payload.get("retention_days", payload)})

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"retention_days": dict(self.days)}, indent=2) + "\n", encoding="utf-8")


def _cutoff(days: int, now: datetime | None = None) -> str:
    return ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()


class SQLiteLifecycle:
    """Export and purge the SQLite stores used by compact/local mode."""

    _TABLES = {
        "jobs": {"jobs": "updated_at", "execution_attempts": "ended_at", "job_transitions": "created_at", "job_idempotency": "created_at", "job_outputs": "created_at"},
        "tasks": {"tasks": "COALESCE(completed_at, issued_at)"},
        "goals": {"goals": "created_at", "goal_events": "created_at"},
        "reviews": {"review_queue": "COALESCE(reviewed_at, created_at)"},
    }

    def __init__(self, stores: Mapping[str, str | Path], *, artifact_store=None) -> None:
        self.stores = {category: Path(path) for category, path in stores.items()}
        self.artifact_store = artifact_store

    def export(self, destination: str | Path, *, now: datetime | None = None) -> Path:
        """Create a portable ZIP containing consistent SQLite copies and a manifest."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {"format": "galaxz-operational-export-v1", "created_at": (now or datetime.now(timezone.utc)).isoformat(), "stores": {}}
        with tempfile.TemporaryDirectory(prefix="galaxz-export-") as temp:
            temp_path = Path(temp)
            for category, source in self.stores.items():
                if not source.exists():
                    continue
                target = temp_path / f"{category}.sqlite"
                src = sqlite3.connect(source)
                dst = sqlite3.connect(target)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                manifest["stores"][category] = {"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size": target.stat().st_size}
            manifest_path = temp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(manifest_path, "manifest.json")
                for file in temp_path.glob("*.sqlite"):
                    archive.write(file, file.name)
        return destination

    def purge_expired(self, policy: RetentionPolicy, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
        deleted: dict[str, int] = {}
        for category, tables in self._TABLES.items():
            source = self.stores.get(category)
            if source is None or not source.exists():
                continue
            connection = sqlite3.connect(source)
            try:
                cutoff = _cutoff(policy.days.get(category, DEFAULT_RETENTION_DAYS[category]), now)
                for table, timestamp in tables.items():
                    count = connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {timestamp} IS NOT NULL AND {timestamp} < ?", (cutoff,)).fetchone()[0]
                    if not dry_run and count:
                        connection.execute(f"DELETE FROM {table} WHERE {timestamp} IS NOT NULL AND {timestamp} < ?", (cutoff,))
                    deleted[table] = deleted.get(table, 0) + count
                if not dry_run:
                    connection.commit()
            finally:
                connection.close()
        if self.artifact_store is not None and "artifacts" in policy.days and not dry_run:
            deleted["artifact_objects"] = len(self.artifact_store.delete_older_than(datetime.fromisoformat(_cutoff(policy.days["artifacts"], now))))
            deleted["artifact_orphans"] = len(self.artifact_store.cleanup_orphans())
        return deleted


def verify_export(path: str | Path) -> dict:
    """Verify manifest checksums without extracting or modifying the archive."""
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for entry in manifest["stores"].values():
            data = archive.read(entry["file"])
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"checksum mismatch for {entry['file']}")
    return manifest
