"""End-to-end safety checks for the repository-to-PR workflow.

These tests use local Git repositories and an HTTP transport stub so they do
not push to a real remote or require GitHub credentials.
"""

import subprocess

import httpx
import pytest

from core.github import GitHubClient, PullRequestEvidence
from workspace.git_changes import commit_artifacts
from workspace.git_workspace import GitWorkspaceManager, WorkspaceError


def _repo(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    (repository / "README").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return repository, base_sha


def _git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True)


def test_concurrent_goals_are_isolated_and_both_anchor_to_same_base(tmp_path):
    repository, base_sha = _repo(tmp_path)
    manager = GitWorkspaceManager(tmp_path / "workspaces")
    first = manager.create(repository, "goal-1", base_sha)
    second = manager.create(repository, "goal-2", base_sha)
    try:
        first_result = commit_artifacts(first.path, [{"filename": "one.txt", "content": "one\n"}], expected_base_sha=base_sha, goal_id="goal-1")
        second_result = commit_artifacts(second.path, [{"filename": "two.txt", "content": "two\n"}], expected_base_sha=base_sha, goal_id="goal-2")
        assert first_result["base_commit_sha"] == second_result["base_commit_sha"] == base_sha
        assert first.branch != second.branch
        assert (tmp_path / "workspaces" / "goal-1" / "two.txt").exists() is False
        assert (tmp_path / "workspaces" / "goal-2" / "one.txt").exists() is False
    finally:
        manager.cleanup(repository, first)
        manager.cleanup(repository, second)


def test_stale_base_and_conflicting_edits_are_rejected_before_merge(tmp_path):
    repository, base_sha = _repo(tmp_path)
    manager = GitWorkspaceManager(tmp_path / "workspaces")
    first = manager.create(repository, "goal-1", base_sha)
    second = manager.create(repository, "goal-2", base_sha)
    try:
        with pytest.raises(WorkspaceError, match="stale"):
            commit_artifacts(first.path, [{"filename": "README", "content": "stale\n"}], expected_base_sha="0" * 40, goal_id="goal-1")
        commit_artifacts(first.path, [{"filename": "README", "content": "first\n"}], expected_base_sha=base_sha, goal_id="goal-1")
        commit_artifacts(second.path, [{"filename": "README", "content": "second\n"}], expected_base_sha=base_sha, goal_id="goal-2")
        _git(repository, "merge", "--no-edit", first.branch)
        merge = subprocess.run(["git", "-C", str(repository), "merge", "--no-commit", second.branch], capture_output=True, text=True)
        assert merge.returncode != 0
        _git(repository, "merge", "--abort")
    finally:
        manager.cleanup(repository, first)
        manager.cleanup(repository, second)


def test_revoked_installation_fails_without_creating_a_pull_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(403, json={"message": "Resource not accessible by integration"}, request=request)

    client = GitHubClient("test-token", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"))
    with pytest.raises(httpx.HTTPStatusError):
        client.create_pull_request(
            "owner", "repo", head="goal-1", base="main", title="Goal", draft=True,
            evidence=PullRequestEvidence("goal-1", ["task-1"], ["README"], "passed", "approved"),
        )
    assert len(requests) == 1
    assert requests[0].url.path == "/repos/owner/repo/pulls"


def test_approved_merge_and_cleanup_complete_the_local_lifecycle(tmp_path):
    repository, base_sha = _repo(tmp_path)
    manager = GitWorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create(repository, "approved-goal", base_sha)
    commit_artifacts(workspace.path, [{"filename": "approved.txt", "content": "approved\n"}], expected_base_sha=base_sha, goal_id="approved-goal")
    _git(repository, "merge", "--no-edit", workspace.branch)
    assert (repository / "approved.txt").read_text(encoding="utf-8") == "approved\n"
    manager.cleanup(repository, workspace)
    assert not (tmp_path / "workspaces" / "approved-goal").exists()
