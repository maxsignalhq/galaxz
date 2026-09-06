"""Short-lived, scoped service identities for internal actors."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceCredential:
    identity: str
    scopes: tuple[str, ...]
    expires_at: float


class ServiceIdentityAuthority:
    def __init__(self, *, secret: bytes | None = None):
        self._secret = secret or secrets.token_bytes(32)
        self._credentials: dict[str, ServiceCredential] = {}
        self._revoked: set[str] = set()

    def issue(self, identity: str, scopes: tuple[str, ...], ttl_seconds: int = 900) -> str:
        if not identity.strip() or not scopes or ttl_seconds <= 0:
            raise ValueError("identity, scopes and positive TTL are required")
        token = secrets.token_urlsafe(32)
        digest = self._digest(token)
        self._credentials[digest] = ServiceCredential(identity, tuple(scopes), time.time() + ttl_seconds)
        return token

    def verify(self, token: str, *, required_scope: str | None = None) -> ServiceCredential:
        digest = self._digest(token)
        credential = self._credentials.get(digest)
        if credential is None or digest in self._revoked or credential.expires_at <= time.time():
            raise PermissionError("service credential is invalid or expired")
        if required_scope is not None and required_scope not in credential.scopes:
            raise PermissionError("service credential lacks required scope")
        return credential

    def revoke(self, token: str) -> None:
        self._revoked.add(self._digest(token))

    def _digest(self, token: str) -> str:
        return hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()
