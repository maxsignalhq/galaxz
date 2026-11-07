import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.accounts.store import AccountError, AccountStore


@pytest.fixture
def store(tmp_path):
    return AccountStore(f"sqlite:///{tmp_path / 'accounts.db'}")


def test_empty_store_has_no_users(store):
    assert store.has_users() is False
    assert store.list_users() == []


def test_create_user_normalises_email_and_creates_default_organization(store):
    user = store.create_user("  Alice@Example.COM ", "operator", display_name="Alice")
    assert user.email == "alice@example.com" and user.role == "operator"
    assert user.organization_id == "default" and user.active is True
    assert store.has_users() is True
    assert [u.email for u in store.list_users()] == ["alice@example.com"]


def test_duplicate_email_and_bad_input_are_rejected(store):
    store.create_user("a@x.io", "viewer")
    with pytest.raises(AccountError, match="already exists"):
        store.create_user("A@X.io", "admin")
    with pytest.raises(AccountError, match="role"):
        store.create_user("b@x.io", "root")
    with pytest.raises(AccountError, match="email"):
        store.create_user("not-an-email", "viewer")


def test_token_authenticates_and_is_stored_hashed(store, tmp_path):
    store.create_user("a@x.io", "reviewer")
    token, record = store.create_token("a@x.io")
    assert token.startswith("gzt_") and record["prefix"] == token[:8]
    principal = store.authenticate(token)
    assert principal.id == "user:a@x.io" and principal.kind == "user"
    assert principal.role == "reviewer" and principal.organization_id == "default"
    with sqlite3.connect(tmp_path / "accounts.db") as db:
        assert token not in str(db.execute("SELECT * FROM api_tokens").fetchall())


def test_unknown_malformed_and_wrong_tokens_do_not_authenticate(store):
    store.create_user("a@x.io", "viewer")
    token, _ = store.create_token("a@x.io")
    for bad in ("", "gzt_nope", token + "x", token[:-1], "Bearer " + token):
        assert store.authenticate(bad) is None


def test_token_role_can_be_downscoped_but_not_escalated(store):
    store.create_user("op@x.io", "operator")
    store.create_user("boss@x.io", "admin")
    token, _ = store.create_token("op@x.io", role="viewer")
    assert store.authenticate(token).role == "viewer"
    with pytest.raises(AccountError, match="exceed"):
        store.create_token("op@x.io", role="admin")
    with pytest.raises(AccountError, match="exceed"):
        store.create_token("op@x.io", role="reviewer")
    token, _ = store.create_token("boss@x.io", role="reviewer")
    assert store.authenticate(token).role == "reviewer"


def test_expired_and_revoked_tokens_and_inactive_users_are_refused(store):
    store.create_user("a@x.io", "operator")
    expired, _ = store.create_token("a@x.io", ttl_days=1)
    with sqlite3.connect(store.url.removeprefix("sqlite:///")) as db:
        db.execute("UPDATE api_tokens SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert store.authenticate(expired) is None

    live, record = store.create_token("a@x.io")
    assert store.authenticate(live) is not None
    store.revoke_token(record["id"])
    assert store.authenticate(live) is None

    again, _ = store.create_token("a@x.io")
    store.deactivate_user("a@x.io")
    assert store.authenticate(again) is None
    with pytest.raises(AccountError, match="inactive"):
        store.create_token("a@x.io")


def test_unknown_user_token_and_revoke_errors(store):
    with pytest.raises(AccountError, match="no such user"):
        store.create_token("ghost@x.io")
    with pytest.raises(AccountError, match="no such token"):
        store.revoke_token("nope")
    with pytest.raises(AccountError, match="no such user"):
        store.deactivate_user("ghost@x.io")


def test_has_users_ignores_deactivated_only_stores_correctly(store):
    store.create_user("a@x.io", "admin")
    store.deactivate_user("a@x.io")
    assert store.has_users() is True  # accounts exist, so auth must stay on
