"""Safe, per-goal Git worktree management."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitWorkspace:
    goal_id: str
    path: str
    branch: str
    base_commit_sha: str


class GitWorkspaceManager:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, repository_path: str | Path, goal_id: str, base_commit_sha: str) -> GitWorkspace:
        repository = Path(repository_path).resolve()
        if not (repository / ".git").exists():
            raise WorkspaceError("repository is not a Git working tree")
        if not re.fullmatch(r"[0-9a-f]{40}", base_commit_sha):
            raise WorkspaceError("base_commit_sha must be a full immutable commit SHA")
        safe_goal = re.sub(r"[^A-Za-z0-9._-]", "-", goal_id).strip("-")
        if not safe_goal:
            raise WorkspaceError("goal_id must contain a usable identifier")
        branch = f"galaxz/goal-{safe_goal}"
        path = (self.root / safe_goal).resolve()
        if not path.is_relative_to(self.root) or path.exists():
            raise WorkspaceError("goal workspace already exists")
        try:
            self._git(repository, "worktree", "add", "-b", branch, str(path), base_commit_sha)
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError("could not create isolated Git workspace") from exc
        workspace = GitWorkspace(goal_id, str(path), branch, base_commit_sha)
        (path / ".galaxz-workspace.json").write_text(json.dumps(workspace.__dict__, indent=2) + "\n", encoding="utf-8")
        return workspace

    def cleanup(self, repository_path: str | Path, workspace: GitWorkspace) -> None:
        path = Path(workspace.path).resolve()
        if not path.is_relative_to(self.root):
            raise WorkspaceError("workspace is outside the manager root")
        try:
            self._git(Path(repository_path).resolve(), "worktree", "remove", "--force", str(path))
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError("could not clean up Git workspace") from exc

    @staticmethod
    def _git(repository: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True)
