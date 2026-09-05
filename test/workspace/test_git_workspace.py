import subprocess

import pytest

from workspace.git_workspace import GitWorkspaceManager, WorkspaceError


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README").write_text("base")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Galaxz", "-c", "user.email=galaxz@example.com", "commit", "-qm", "base"], check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return repo, sha


def test_goal_workspaces_are_isolated_and_pinned(tmp_path):
    repo, sha = _repo(tmp_path)
    manager = GitWorkspaceManager(tmp_path / "workspaces")
    first = manager.create(repo, "goal-1", sha)
    second = manager.create(repo, "goal-2", sha)
    assert first.path != second.path
    assert first.branch != second.branch
    assert (tmp_path / "workspaces" / "goal-1" / ".galaxz-workspace.json").exists()
    assert subprocess.run(["git", "-C", first.path, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip() == sha
    manager.cleanup(repo, first)
    manager.cleanup(repo, second)


def test_workspace_rejects_non_immutable_base_and_interrupted_cleanup(tmp_path):
    repo, _ = _repo(tmp_path)
    manager = GitWorkspaceManager(tmp_path / "workspaces")
    with pytest.raises(WorkspaceError, match="full immutable"):
        manager.create(repo, "goal", "HEAD")
    with pytest.raises(WorkspaceError, match="outside"):
        manager.cleanup(repo, type("Workspace", (), {"path": "/tmp/elsewhere"})())
