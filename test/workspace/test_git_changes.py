import subprocess

import pytest

from workspace.git_changes import commit_artifacts
from workspace.git_workspace import WorkspaceError


def test_commit_artifacts_has_canonical_diff_and_provenance(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README").write_text("base")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    result = commit_artifacts(repo, [{"filename": "src/out.py", "content": "print(1)\n"}], expected_base_sha=base, goal_id="goal-1")
    assert result["base_commit_sha"] == base
    assert result["goal_id"] == "goal-1"
    assert "src/out.py" in result["diff"]
    assert subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"], check=True, capture_output=True, text=True).stdout.strip() == "galaxz: apply goal goal-1 artifacts"


def test_stale_base_is_rejected(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README").write_text("base")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"], check=True)
    with pytest.raises(WorkspaceError, match="stale"):
        commit_artifacts(repo, [{"filename": "x", "content": "x"}], expected_base_sha="0" * 40, goal_id="goal")
