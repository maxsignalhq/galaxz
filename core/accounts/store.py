"""Organizations, users and API tokens.

SQLite (local mode) creates its tables here; PostgreSQL schema is owned by Alembic
(``0006_accounts``) and is never altered at runtime.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .permissions import ROLES

DEFAULT_ORGANIZATION = "default"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SQLITE_DDL = (
    "CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id), "
    "email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL, "
    "active BOOLEAN NOT NULL DEFAULT TRUE, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS api_tokens (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), "
    "token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, role TEXT NOT NULL, expires_at TEXT, "
    "revoked_at TEXT, created_at TEXT NOT NULL)",
)


class AccountError(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: str
    organization_id: str
    email: str
    display_name: str
    role: str
    active: bool
    created_at: str


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str
    organization_id: str
    role: str

    def as_state(self) -> dict:
        return {"id": self.id, "kind": self.kind, "organization_id": self.organization_id, "role": self.role}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _may_issue(user_role: str, token_role: str) -> bool:
    return token_role == user_role or token_role == "viewer" or user_role == "admin"


class AccountStore:
    def __init__(self, url: str, *, engine: Engine | None = None):
        self.url = url
        self.engine = engine or create_engine(url, pool_pre_ping=True, hide_parameters=True)
        self._lock = threading.Lock()
        if self.engine.dialect.name == "sqlite":
            with self.engine.begin() as c:
                for ddl in _SQLITE_DDL:
                    c.execute(text(ddl))

    @staticmethod
    def _user(row) -> User:
        return User(row["id"], row["organization_id"], row["email"], row["display_name"], row["role"], bool(row["active"]), row["created_at"])

    def has_users(self) -> bool:
        with self.engine.connect() as c:
            return c.execute(text("SELECT 1 FROM users LIMIT 1")).first() is not None

    def list_users(self) -> list[User]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM users ORDER BY created_at, email")).mappings().all()
        return [self._user(row) for row in rows]

    def ensure_organization(self, organization_id: str = DEFAULT_ORGANIZATION, name: str = "Default") -> None:
        with self._lock, self.engine.begin() as c:
            if c.execute(text("SELECT 1 FROM organizations WHERE id=:id"), {"id": organization_id}).first() is None:
                c.execute(text("INSERT INTO organizations (id, name, created_at) VALUES (:id, :name, :at)"),
                          {"id": organization_id, "name": name, "at": _now().isoformat()})

    def create_user(self, email: str, role: str, *, display_name: str = "", organization_id: str = DEFAULT_ORGANIZATION) -> User:
        email = email.strip().lower()
        if not _EMAIL.match(email):
            raise AccountError(f"invalid email: {email!r}")
        if role not in ROLES:
            raise AccountError(f"role must be one of {', '.join(sorted(ROLES))}")
        self.ensure_organization(organization_id)
        user_id = str(uuid4())
        with self._lock, self.engine.begin() as c:
            if c.execute(text("SELECT 1 FROM users WHERE email=:e"), {"e": email}).first() is not None:
                raise AccountError(f"user {email} already exists")
            c.execute(
                text("INSERT INTO users (id, organization_id, email, display_name, role, active, created_at) "
                     "VALUES (:id, :org, :email, :name, :role, :active, :at)"),
                {"id": user_id, "org": organization_id, "email": email, "name": display_name, "role": role,
                 "active": True, "at": _now().isoformat()},
            )
            row = c.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id}).mappings().one()
        return self._user(row)

    def _get_user(self, c, email: str):
        return c.execute(text("SELECT * FROM users WHERE email=:e"), {"e": email.strip().lower()}).mappings().first()

    def deactivate_user(self, email: str) -> None:
        with self._lock, self.engine.begin() as c:
            if self._get_user(c, email) is None:
                raise AccountError(f"no such user: {email}")
            c.execute(text("UPDATE users SET active=:a WHERE email=:e"), {"a": False, "e": email.strip().lower()})

    def create_token(self, email: str, *, role: str | None = None, ttl_days: int | None = None) -> tuple[str, dict]:
        """Return ``(plaintext_token, record)``. The plaintext is never stored and cannot be recovered."""
        with self._lock, self.engine.begin() as c:
            user = self._get_user(c, email)
            if user is None:
                raise AccountError(f"no such user: {email}")
            if not user["active"]:
                raise AccountError(f"user {email} is inactive")
            role = role or user["role"]
            if role not in ROLES:
                raise AccountError(f"role must be one of {', '.join(sorted(ROLES))}")
            if not _may_issue(user["role"], role):
                raise AccountError(f"token role {role} would exceed the user's role {user['role']}")
            token = "gzt_" + secrets.token_urlsafe(32)
            record = {
                "id": str(uuid4()), "user_id": user["id"], "prefix": token[:8], "role": role,
                "expires_at": (_now() + timedelta(days=ttl_days)).isoformat() if ttl_days else None,
                "created_at": _now().isoformat(),
            }
            c.execute(
                text("INSERT INTO api_tokens (id, user_id, token_hash, prefix, role, expires_at, created_at) "
                     "VALUES (:id, :user_id, :hash, :prefix, :role, :expires_at, :created_at)"),
                {**record, "hash": _hash(token)},
            )
        return token, record

    def list_tokens(self, email: str) -> list[dict]:
        """Token metadata for a user (never the token itself)."""
        with self.engine.connect() as c:
            rows = c.execute(
                text("SELECT t.id, t.prefix, t.role, t.expires_at, t.revoked_at, t.created_at FROM api_tokens t "
                     "JOIN users u ON u.id = t.user_id WHERE u.email=:e ORDER BY t.created_at"),
                {"e": email.strip().lower()},
            ).mappings().all()
        return [dict(row) for row in rows]

    def revoke_token(self, token_id: str) -> None:
        with self._lock, self.engine.begin() as c:
            if c.execute(text("SELECT 1 FROM api_tokens WHERE id=:id"), {"id": token_id}).first() is None:
                raise AccountError(f"no such token: {token_id}")
            c.execute(text("UPDATE api_tokens SET revoked_at=:at WHERE id=:id AND revoked_at IS NULL"),
                      {"at": _now().isoformat(), "id": token_id})

    def authenticate(self, token: str) -> Principal | None:
        if not token or not token.startswith("gzt_"):
            return None
        with self.engine.connect() as c:
            row = c.execute(
                text("SELECT t.role AS role, t.expires_at AS expires_at, t.revoked_at AS revoked_at, "
                     "u.email AS email, u.organization_id AS org, u.active AS active "
                     "FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash=:h"),
                {"h": _hash(token)},
            ).mappings().first()
        if row is None or row["revoked_at"] is not None or not row["active"]:
            return None
        if row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
        return Principal(f"user:{row['email']}", "user", row["org"], row["role"])
