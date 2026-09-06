import sqlite3

import pytest
from cryptography.fernet import Fernet

from core.secrets import SecretScope, SecretStore, redact_secrets


class Provider:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


def scope(task="task-1"):
    return SecretScope("org-1", "repo-1", task, "deny-all")


def test_secret_reference_is_encrypted_and_scope_bound(tmp_path):
    store = SecretStore(tmp_path / "secrets.db", Provider(Fernet.generate_key()))
    reference = store.put("super-secret-value", scope())
    assert "super-secret-value" not in str(reference)
    assert store.resolve(reference["secret_id"], scope()) == "super-secret-value"
    with pytest.raises(PermissionError):
        store.resolve(reference["secret_id"], scope("other-task"))
    with sqlite3.connect(tmp_path / "secrets.db") as db:
        assert "super-secret-value" not in str(db.execute("SELECT ciphertext FROM secret_references").fetchone())


def test_secret_redaction_is_deterministic():
    assert redact_secrets("token=abc password=xyz", ["abc", "xyz"]) == "token=[REDACTED] password=[REDACTED]"
