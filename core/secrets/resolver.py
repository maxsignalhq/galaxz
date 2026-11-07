"""Resolve ``${{ secrets.<id> }}`` payload references at the moment of tool execution."""

from __future__ import annotations

import os
import re
import threading
from typing import Callable

from .store import EnvironmentKeyProvider, SecretScope, SecretStore, redact_secrets

# Prompt-driven skills would put the value in an LLM prompt and in generated artifacts.
SECRET_SKILL_PREFIXES = ("quasar.",)

_REFERENCE = re.compile(r"^\$\{\{\s*secrets\.([A-Za-z0-9_-]+)\s*}}$")


class SecretResolutionError(Exception):
    """``reason`` is a fixed, safe-to-log code; the message never carries secret detail."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _has_reference(value) -> bool:
    if isinstance(value, dict):
        return any(_has_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_reference(item) for item in value)
    return isinstance(value, str) and _REFERENCE.match(value) is not None


def redact_structure(data, values):
    """Replace every secret value inside the strings of a nested structure (dict keys untouched)."""
    values = [value for value in values if value]
    if not values:
        return data

    def walk(item):
        if isinstance(item, dict):
            return {key: walk(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [walk(inner) for inner in item]
        if isinstance(item, str):
            return redact_secrets(item, values)
        return item

    return walk(data)


def configured_organization_id() -> str:
    return os.getenv("GALAXZ_ORGANIZATION_ID", "default")


def open_default_store() -> SecretStore:
    return SecretStore(os.getenv("GALAXZ_SECRETS_DB", "data/secrets.db"), EnvironmentKeyProvider())


class SecretResolver:
    def __init__(self, store_factory: Callable[[], SecretStore] | None = None, organization_id: str | None = None):
        self._store_factory = store_factory or open_default_store
        self.organization_id = organization_id or configured_organization_id()
        self._store: SecretStore | None = None
        self._lock = threading.Lock()

    def _open(self) -> SecretStore:
        with self._lock:
            if self._store is None:
                try:
                    self._store = self._store_factory()
                except Exception as exc:
                    raise SecretResolutionError("secret_store_unavailable") from exc
            return self._store

    def resolve(
        self, payload: dict, *, skill_id: str, repository_id: str, task_id: str, organization_id: str | None = None
    ) -> tuple[dict, list[str]]:
        """Return ``(payload_with_values, values)``; the input is never mutated.

        A task from a non-default organization resolves only that organization's secrets. A ``default``
        task keeps using the configured ``GALAXZ_ORGANIZATION_ID`` so existing single-tenant setups are unchanged.
        """
        organization_id = organization_id if organization_id not in (None, "default") else self.organization_id
        if not _has_reference(payload):
            return payload, []
        if not skill_id.startswith(SECRET_SKILL_PREFIXES):
            raise SecretResolutionError("secret_not_permitted_for_skill")
        store = self._open()
        scope = SecretScope(organization_id, repository_id, task_id, skill_id)
        values: list[str] = []

        def resolve_one(secret_id: str) -> str:
            try:
                value = store.resolve(secret_id, scope)
            except PermissionError as exc:
                raise SecretResolutionError("secret_reference_unavailable") from exc
            except Exception as exc:  # unreadable database, wrong key, corrupt ciphertext
                raise SecretResolutionError("secret_store_unavailable") from exc
            if value not in values:
                values.append(value)
            return value

        def walk(item):
            if isinstance(item, dict):
                return {key: walk(inner) for key, inner in item.items()}
            if isinstance(item, list):
                return [walk(inner) for inner in item]
            if isinstance(item, str):
                match = _REFERENCE.match(item)
                if match:
                    return resolve_one(match.group(1))
            return item

        return walk(payload), values
