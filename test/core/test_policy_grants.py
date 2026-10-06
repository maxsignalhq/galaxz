import os
import time

from core.policy import GrantStore


def _store(tmp_path):
    return GrantStore(str(tmp_path / "policy.db"))


def test_database_file_is_not_created_until_used(tmp_path):
    path = tmp_path / "sub" / "policy.db"
    store = GrantStore(str(path))
    assert not path.exists()
    store.consume(origin="o", skill="s", digest="d")
    assert path.exists()


def test_grant_is_single_use(tmp_path):
    store = _store(tmp_path)
    store.issue(origin="o", skill="s", digest="d")
    assert store.consume(origin="o", skill="s", digest="d") is True
    assert store.consume(origin="o", skill="s", digest="d") is False


def test_each_issued_grant_is_consumed_once(tmp_path):
    store = _store(tmp_path)
    store.issue(origin="o", skill="s", digest="d")
    store.issue(origin="o", skill="s", digest="d")
    assert [store.consume(origin="o", skill="s", digest="d") for _ in range(3)] == [True, True, False]


def test_grant_only_matches_exact_origin_skill_and_digest(tmp_path):
    store = _store(tmp_path)
    store.issue(origin="o", skill="s", digest="d")
    assert store.consume(origin="other", skill="s", digest="d") is False
    assert store.consume(origin="o", skill="other", digest="d") is False
    assert store.consume(origin="o", skill="s", digest="other") is False
    assert store.consume(origin="o", skill="s", digest="d") is True


def test_expired_grant_is_not_usable(tmp_path):
    store = _store(tmp_path)
    store.issue(origin="o", skill="s", digest="d", ttl_s=0)
    time.sleep(0.01)
    assert store.consume(origin="o", skill="s", digest="d") is False


def test_grants_survive_a_new_store_instance(tmp_path):
    _store(tmp_path).issue(origin="o", skill="s", digest="d", granted_by="review")
    assert _store(tmp_path).consume(origin="o", skill="s", digest="d") is True


def test_default_path_comes_from_environment(tmp_path, monkeypatch):
    target = tmp_path / "env-policy.db"
    monkeypatch.setenv("POLICY_DB_PATH", str(target))
    GrantStore().issue(origin="o", skill="s", digest="d")
    assert os.path.exists(target)
