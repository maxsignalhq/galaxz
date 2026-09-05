"""Repository registration and immutable local Git revision resolution."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class RepositoryAccessError(PermissionError):
    """Raised when repository metadata or revisions cannot be accessed."""


@dataclass(frozen=True)
class RepositoryRecord:
    repository_id: str
    provider: str
    owner: str
    name: str
    installation_scope: str
    local_path: str | None
    active: bool
    created_at: str


class RepositoryStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("REPOSITORY_DB_PATH", "data/repositories.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""CREATE TABLE IF NOT EXISTS repositories (
            repository_id TEXT PRIMARY KEY, provider TEXT NOT NULL, owner TEXT NOT NULL,
            name TEXT NOT NULL, installation_scope TEXT NOT NULL, local_path TEXT,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            UNIQUE(provider, owner, name, installation_scope))""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS repository_revisions (
            repository_id TEXT NOT NULL, requested_revision TEXT NOT NULL,
            commit_sha TEXT NOT NULL, resolved_at TEXT NOT NULL,
            PRIMARY KEY(repository_id, requested_revision),
            FOREIGN KEY(repository_id) REFERENCES repositories(repository_id))""")
        self._conn.commit()

    def register(self, *, provider: str, owner: str, name: str, installation_scope: str, local_path: str | None = None) -> RepositoryRecord:
        values = [value.strip() for value in (provider, owner, name, installation_scope)]
        if not all(values):
            raise ValueError("provider, owner, name and installation_scope are required")
        if local_path is not None and not Path(local_path).is_dir():
            raise RepositoryAccessError("repository path does not exist or is not a directory")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute("""INSERT INTO repositories
                (repository_id,provider,owner,name,installation_scope,local_path,created_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(provider,owner,name,installation_scope) DO UPDATE SET
                local_path=excluded.local_path, active=1""", (str(uuid4()), *values, local_path, now))
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM repositories WHERE provider=? AND owner=? AND name=? AND installation_scope=?", values).fetchone()
        return self._record(row)

    def get(self, repository_id: str, *, access_checker=None) -> RepositoryRecord:
        with self._lock:
            row = self._conn.execute("SELECT * FROM repositories WHERE repository_id=?", (repository_id,)).fetchone()
        if row is None or not row["active"]:
            raise RepositoryAccessError("repository is deleted or inaccessible")
        record = self._record(row)
        if access_checker is not None and not access_checker(record):
            raise RepositoryAccessError("repository access denied")
        return record

    def resolve_base(self, repository_id: str, revision: str = "HEAD", *, access_checker=None) -> str:
        record = self.get(repository_id, access_checker=access_checker)
        if not record.local_path:
            raise RepositoryAccessError("repository has no configured provider resolver")
        try:
            sha = subprocess.run(["git", "-C", record.local_path, "rev-parse", "--verify", f"{revision}^{{commit}}"], check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RepositoryAccessError("repository revision is unavailable") from exc
        if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha.lower()):
            raise RepositoryAccessError("repository returned an invalid commit SHA")
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO repository_revisions VALUES (?,?,?,?)", (repository_id, revision, sha, datetime.now(timezone.utc).isoformat()))
            self._conn.commit()
        return sha

    @staticmethod
    def _record(row: sqlite3.Row) -> RepositoryRecord:
        return RepositoryRecord(row["repository_id"], row["provider"], row["owner"], row["name"], row["installation_scope"], row["local_path"], bool(row["active"]), row["created_at"])
