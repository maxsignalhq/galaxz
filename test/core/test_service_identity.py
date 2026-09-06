import pytest

from core.security import ServiceIdentityAuthority


def test_service_identity_is_scoped_rotatable_and_revocable():
    authority = ServiceIdentityAuthority(secret=b"stable-test-secret")
    first = authority.issue("worker-1", ("jobs:claim",), ttl_seconds=60)
    assert first != authority.issue("worker-1", ("jobs:claim",), ttl_seconds=60)
    assert authority.verify(first, required_scope="jobs:claim").identity == "worker-1"
    with pytest.raises(PermissionError):
        authority.verify(first, required_scope="admin")
    authority.revoke(first)
    with pytest.raises(PermissionError):
        authority.verify(first)


def test_expired_service_identity_is_rejected(monkeypatch):
    authority = ServiceIdentityAuthority(secret=b"stable-test-secret")
    token = authority.issue("agent-1", ("tasks:run",), ttl_seconds=1)
    now = time = __import__("time")
    monkeypatch.setattr(now, "time", lambda: 1000)
    authority = ServiceIdentityAuthority(secret=b"stable-test-secret")
    token = authority.issue("agent-1", ("tasks:run",), ttl_seconds=1)
    monkeypatch.setattr(now, "time", lambda: 1002)
    with pytest.raises(PermissionError):
        authority.verify(token)
