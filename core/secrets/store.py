"""Encrypted, scope-bound secret references."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class ManagedKeyProvider(Protocol):
    def key(self) -> bytes: ...


class EnvironmentKeyProvider:
    def key(self) -> bytes:
        value = os.getenv("GALAXZ_SECRETS_KEY")
        if not value:
            raise RuntimeError("GALAXZ_SECRETS_KEY is not configured")
        return value.encode()


@dataclass(frozen=True)
class SecretScope:
    organization_id: str
    repository_id: str
    task_id: str
    policy: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        values = (self.organization_id, self.repository_id, self.task_id, self.policy)
        if not all(value.strip() for value in values):
            raise ValueError("all secret scope fields are required")
        return values


class SecretStore:
    def __init__(self, path: str | Path, key_provider: ManagedKeyProvider):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise RuntimeError("cryptography is required for encrypted secret storage") from exc
        self._fernet = Fernet(key_provider.key())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS secret_references (secret_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, repository_id TEXT NOT NULL, task_id TEXT NOT NULL, policy TEXT NOT NULL, ciphertext BLOB NOT NULL, created_at TEXT NOT NULL)")
        self._db.commit()

    def put(self, value: str, scope: SecretScope) -> dict:
        if not value:
            raise ValueError("secret value must not be empty")
        organization, repository, task, policy = scope.as_tuple()
        secret_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        ciphertext = self._fernet.encrypt(value.encode())
        self._db.execute("INSERT INTO secret_references VALUES (?, ?, ?, ?, ?, ?, ?)", (secret_id, organization, repository, task, policy, ciphertext, created_at))
        self._db.commit()
        return {"secret_id": secret_id, "organization_id": organization, "repository_id": repository, "task_id": task, "policy": policy, "created_at": created_at}

    def resolve(self, secret_id: str, scope: SecretScope) -> str:
        row = self._db.execute("SELECT organization_id,repository_id,task_id,policy,ciphertext FROM secret_references WHERE secret_id=?", (secret_id,)).fetchone()
        if row is None or tuple(row[:4]) != scope.as_tuple():
            raise PermissionError("secret reference is unavailable for this scope")
        return self._fernet.decrypt(row[4]).decode()


def redact_secrets(text: str, values: list[str] | tuple[str, ...]) -> str:
    redacted = text
    for value in values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
