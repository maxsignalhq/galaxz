import subprocess

import pytest

from core.repositories import RepositoryAccessError, RepositoryStore


def test_register_resolve_pins_sha_and_checks_access(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README").write_text("one")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial"], check=True)
    store = RepositoryStore(str(tmp_path / "repositories.db"))
    record = store.register(provider="github", owner="astro", name="galaxz", installation_scope="install-1", local_path=str(repo))
    with pytest.raises(RepositoryAccessError):
        store.resolve_base(record.repository_id, access_checker=lambda _: False)
    sha = store.resolve_base(record.repository_id, access_checker=lambda _: True)
    assert len(sha) == 40
    (repo / "README").write_text("moved")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "second"], check=True)
    assert store.resolve_base(record.repository_id, "HEAD~1") == sha


def test_missing_revision_and_path_fail_closed(tmp_path):
    store = RepositoryStore(str(tmp_path / "repositories.db"))
    with pytest.raises(RepositoryAccessError):
        store.register(provider="github", owner="a", name="b", installation_scope="i", local_path=str(tmp_path / "missing"))
