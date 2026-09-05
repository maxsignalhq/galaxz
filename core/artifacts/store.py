from __future__ import annotations

import difflib
import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone

from core.artifacts.object_storage import ArtifactAccessPolicy, ObjectStorage


def identity_key(workspace_root: str, filename: str) -> str:
    return f"{workspace_root}::{filename}"


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS artifact_versions (
    identity_key   TEXT    NOT NULL,
    version        INTEGER NOT NULL,
    content        TEXT    NOT NULL,
    content_hash   TEXT    NOT NULL,
    filename       TEXT    NOT NULL,
    language       TEXT,
    artifact_type  TEXT,
    task_id        TEXT    NOT NULL,
    skill          TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    attempt_artifact_key TEXT,
    PRIMARY KEY (identity_key, version)
)
"""


class ArtifactStore:
    def __init__(self, db_path: str = "data/artifacts.db", *, object_storage: ObjectStorage | None = None):
        self._lock = threading.Lock()
        self.object_storage = object_storage
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(artifact_versions)")}
        if "attempt_artifact_key" not in columns:
            self._conn.execute("ALTER TABLE artifact_versions ADD COLUMN attempt_artifact_key TEXT")
        for column, definition in (
            ("object_id", "TEXT"),
            ("object_size_bytes", "INTEGER"),
            ("media_type", "TEXT"),
            ("project_id", "TEXT"),
            ("organization_id", "TEXT"),
        ):
            if column not in columns:
                self._conn.execute(f"ALTER TABLE artifact_versions ADD COLUMN {column} {definition}")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS artifact_attempt_identity "
            "ON artifact_versions(attempt_artifact_key) WHERE attempt_artifact_key IS NOT NULL"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS artifact_attempt_versions ("
            "attempt_artifact_key TEXT PRIMARY KEY, identity_key TEXT NOT NULL, version INTEGER NOT NULL)"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO artifact_attempt_versions "
            "SELECT attempt_artifact_key, identity_key, version FROM artifact_versions "
            "WHERE attempt_artifact_key IS NOT NULL"
        )
        self._conn.commit()

    def record(
        self,
        artifacts: list[dict],
        workspace_root: str,
        task_id: str,
        skill: str,
        attempt_id: str | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
    ) -> list[dict]:
        results = []
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            for artifact in artifacts:
                filename = artifact["filename"]
                content = artifact["content"]
                key = identity_key(workspace_root, filename)
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                attempt_key = f"{attempt_id}::{key}" if attempt_id else None

                if attempt_key is not None:
                    prior_attempt = self._conn.execute(
                        "SELECT identity_key, version FROM artifact_attempt_versions "
                        "WHERE attempt_artifact_key = ?",
                        (attempt_key,),
                    ).fetchone()
                    if prior_attempt is not None:
                        results.append({
                            "identity_key": prior_attempt["identity_key"],
                            "version": prior_attempt["version"],
                            "recorded": False,
                        })
                        continue

                cur = self._conn.execute(
                    "SELECT content_hash, version FROM artifact_versions "
                    "WHERE identity_key = ? ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                row = cur.fetchone()

                if row is not None and row["content_hash"] == content_hash:
                    if attempt_key is not None:
                        self._conn.execute(
                            "INSERT INTO artifact_attempt_versions VALUES (?, ?, ?)",
                            (attempt_key, key, row["version"]),
                        )
                    results.append({"identity_key": key, "version": row["version"], "recorded": False})
                    continue

                next_version = (row["version"] if row is not None else 0) + 1
                object_metadata = None
                if self.object_storage is not None:
                    object_id = f"{key}/v{next_version}"
                    object_metadata = self.object_storage.put(
                        object_id, content.encode("utf-8"),
                        media_type=artifact.get("media_type"),
                    )
                try:
                    self._conn.execute(
                        "INSERT INTO artifact_versions "
                    "(identity_key, version, content, content_hash, filename, language, "
                    "artifact_type, task_id, skill, created_at, attempt_artifact_key, "
                    "object_id, object_size_bytes, media_type, project_id, organization_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        next_version,
                        content,
                        content_hash,
                        filename,
                        artifact.get("language"),
                        artifact.get("artifact_type"),
                        task_id,
                        skill,
                        now,
                        attempt_key,
                        object_metadata.object_id if object_metadata else None,
                        object_metadata.size_bytes if object_metadata else None,
                        object_metadata.media_type if object_metadata else None,
                        project_id,
                        organization_id,
                    ),
                    )
                except Exception:
                    if object_metadata is not None:
                        self.object_storage.delete(object_metadata.object_id)
                    raise
                if attempt_key is not None:
                    self._conn.execute(
                        "INSERT INTO artifact_attempt_versions VALUES (?, ?, ?)",
                        (attempt_key, key, next_version),
                    )
                results.append({"identity_key": key, "version": next_version, "recorded": True})
        return results

    def list_files(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT identity_key, filename, version, task_id, created_at "
                "FROM artifact_versions ORDER BY identity_key, version DESC"
            )
            latest: dict[str, dict] = {}
            for row in cur.fetchall():
                key = row["identity_key"]
                if key in latest:
                    continue
                latest[key] = {
                    "identity_key": key,
                    "filename": row["filename"],
                    "latest_version": row["version"],
                    "updated_at": row["created_at"],
                    "task_id": row["task_id"],
                }
            return list(latest.values())

    def history(self, identity_key_value: str) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT version, task_id, skill, created_at, content_hash "
                "FROM artifact_versions WHERE identity_key = ? ORDER BY version DESC",
                (identity_key_value,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_version(self, identity_key_value: str, version: int, *, project_id: str | None = None, organization_id: str | None = None) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM artifact_versions WHERE identity_key = ? AND version = ?",
                (identity_key_value, version),
            )
            row = cur.fetchone()
            result = dict(row) if row is not None else None
        if result is not None and self.object_storage is not None and result.get("object_id"):
            ArtifactAccessPolicy().authorize(
                artifact_project_id=result.get("project_id"),
                artifact_organization_id=result.get("organization_id"),
                project_id=project_id,
                organization_id=organization_id,
            )
            result["content"] = self.object_storage.get(result["object_id"]).decode("utf-8")
        return result

    def latest_version_number(self, identity_key_value: str) -> int | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT MAX(version) AS v FROM artifact_versions WHERE identity_key = ?",
                (identity_key_value,),
            )
            value = cur.fetchone()["v"]
            return value

    def cleanup_orphans(self) -> list[str]:
        """Delete backend objects that have no committed metadata row."""
        if self.object_storage is None:
            return []
        with self._lock:
            rows = self._conn.execute("SELECT object_id FROM artifact_versions WHERE object_id IS NOT NULL").fetchall()
        known = {row[0] for row in rows}
        deleted = []
        for object_id in self.object_storage.list_ids():
            if object_id not in known:
                self.object_storage.delete(object_id)
                deleted.append(object_id)
        return deleted

    def delete_older_than(self, cutoff: datetime) -> list[str]:
        """Remove old versions and their payloads, retaining current versions."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT identity_key, version, object_id FROM artifact_versions "
                "WHERE created_at < ? AND version < (SELECT MAX(v.version) FROM artifact_versions v WHERE v.identity_key = artifact_versions.identity_key)",
                (cutoff.isoformat(),),
            ).fetchall()
            self._conn.executemany("DELETE FROM artifact_versions WHERE identity_key = ? AND version = ?", [(row[0], row[1]) for row in rows])
            self._conn.commit()
        deleted = []
        if self.object_storage is not None:
            for _, _, object_id in rows:
                if object_id:
                    self.object_storage.delete(object_id)
                    deleted.append(object_id)
        return deleted

    def diff(self, identity_key_value: str, from_version: int, to_version: int) -> str:
        from_row = self.get_version(identity_key_value, from_version)
        to_row = self.get_version(identity_key_value, to_version)
        if from_row is None or to_row is None:
            raise KeyError(f"version not found for {identity_key_value}: {from_version} or {to_version}")

        diff_lines = difflib.unified_diff(
            from_row["content"].splitlines(keepends=True),
            to_row["content"].splitlines(keepends=True),
            fromfile=f"{identity_key_value}@v{from_version}",
            tofile=f"{identity_key_value}@v{to_version}",
        )
        return "".join(diff_lines)
