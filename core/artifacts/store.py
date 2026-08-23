from __future__ import annotations

import difflib
import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone


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
    PRIMARY KEY (identity_key, version)
)
"""


class ArtifactStore:
    def __init__(self, db_path: str = "data/artifacts.db"):
        self._lock = threading.Lock()
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def record(
        self,
        artifacts: list[dict],
        workspace_root: str,
        task_id: str,
        skill: str,
    ) -> list[dict]:
        results = []
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for artifact in artifacts:
                filename = artifact["filename"]
                content = artifact["content"]
                key = identity_key(workspace_root, filename)
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                cur = self._conn.execute(
                    "SELECT content_hash, version FROM artifact_versions "
                    "WHERE identity_key = ? ORDER BY version DESC LIMIT 1",
                    (key,),
                )
                row = cur.fetchone()

                if row is not None and row["content_hash"] == content_hash:
                    results.append({"identity_key": key, "version": row["version"], "recorded": False})
                    continue

                next_version = (row["version"] if row is not None else 0) + 1
                self._conn.execute(
                    "INSERT INTO artifact_versions "
                    "(identity_key, version, content, content_hash, filename, language, "
                    "artifact_type, task_id, skill, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
                )
                self._conn.commit()
                results.append({"identity_key": key, "version": next_version, "recorded": True})
        return results

    def list_files(self) -> list[dict]:
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
        cur = self._conn.execute(
            "SELECT version, task_id, skill, created_at, content_hash "
            "FROM artifact_versions WHERE identity_key = ? ORDER BY version DESC",
            (identity_key_value,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_version(self, identity_key_value: str, version: int) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM artifact_versions WHERE identity_key = ? AND version = ?",
            (identity_key_value, version),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def latest_version_number(self, identity_key_value: str) -> int | None:
        cur = self._conn.execute(
            "SELECT MAX(version) AS v FROM artifact_versions WHERE identity_key = ?",
            (identity_key_value,),
        )
        value = cur.fetchone()["v"]
        return value

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
