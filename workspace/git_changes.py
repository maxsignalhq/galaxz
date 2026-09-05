"""Canonical diffs and provenance commits for an isolated Git workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .git_workspace import WorkspaceError


def canonical_diff(workspace_path: str | Path) -> str:
    return subprocess.run(["git", "-C", str(workspace_path), "diff", "HEAD", "--binary", "--no-ext-diff"], check=True, capture_output=True, text=True).stdout


def commit_artifacts(workspace_path: str | Path, artifacts: list[dict], *, expected_base_sha: str, goal_id: str, author_name: str = "Galaxz", author_email: str = "galaxz@example.com") -> dict:
    workspace = Path(workspace_path).resolve()
    current = subprocess.run(["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if current != expected_base_sha:
        raise WorkspaceError("workspace base changed; refusing to commit a stale goal")
    for artifact in artifacts:
        target = (workspace / artifact["filename"]).resolve()
        if not target.is_relative_to(workspace):
            raise WorkspaceError("artifact path escapes the isolated workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact["content"], encoding="utf-8")
        subprocess.run(["git", "-C", str(workspace), "add", "--", artifact["filename"]], check=True, capture_output=True, text=True)
    diff = canonical_diff(workspace)
    if not diff:
        raise WorkspaceError("no changes to commit")
    message = f"galaxz: apply goal {goal_id} artifacts"
    subprocess.run(["git", "-C", str(workspace), "-c", f"user.name={author_name}", "-c", f"user.email={author_email}", "commit", "-m", message], check=True, capture_output=True, text=True)
    commit_sha = subprocess.run(["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return {"commit_sha": commit_sha, "base_commit_sha": expected_base_sha, "goal_id": goal_id, "diff": diff, "message": message}
