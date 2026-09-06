"""Least-leaky GitHub pull-request and check-run integration primitives."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


@dataclass(frozen=True)
class PullRequestEvidence:
    goal_id: str
    task_ids: list[str]
    artifacts: list[str]
    validation: str
    review_decision: str


def build_pr_body(evidence: PullRequestEvidence) -> str:
    tasks = ", ".join(f"`{value}`" for value in evidence.task_ids) or "none"
    artifacts = ", ".join(f"`{value}`" for value in evidence.artifacts) or "none"
    return (f"## Galaxz execution evidence\n\n- Goal: `{evidence.goal_id}`\n"
            f"- Tasks: {tasks}\n- Artifacts: {artifacts}\n"
            f"- Validation: {evidence.validation}\n- Review decision: {evidence.review_decision}\n")


class GitHubClient:
    def __init__(self, token: str, *, base_url: str = "https://api.github.com", client: httpx.Client | None = None):
        if not token or any(char.isspace() for char in token):
            raise ValueError("a non-empty GitHub token is required")
        self._client = client or httpx.Client(base_url=base_url, timeout=20)
        self._client.headers.update({"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})

    def create_pull_request(self, owner: str, repo: str, *, head: str, base: str, title: str, evidence: PullRequestEvidence, draft: bool = True) -> dict:
        response = self._client.post(f"/repos/{owner}/{repo}/pulls", json={"title": title, "head": head, "base": base, "body": build_pr_body(evidence), "draft": draft})
        response.raise_for_status()
        return response.json()

    def create_check_run(self, owner: str, repo: str, *, head_sha: str, name: str, passed: bool, summary: str) -> dict:
        response = self._client.post(f"/repos/{owner}/{repo}/check-runs", json={"name": name, "head_sha": head_sha, "status": "completed", "conclusion": "success" if passed else "failure", "output": {"title": name, "summary": summary[:10000]}})
        response.raise_for_status()
        return response.json()


class WebhookStore:
    """Small idempotency ledger for replayed GitHub deliveries."""

    def __init__(self, path: str | Path):
        self._connection = sqlite3.connect(path)
        self._connection.execute("CREATE TABLE IF NOT EXISTS github_webhooks (delivery_id TEXT PRIMARY KEY, action TEXT NOT NULL, processed_at TEXT NOT NULL)")
        self._connection.execute("CREATE TABLE IF NOT EXISTS github_pull_requests (number INTEGER PRIMARY KEY, state TEXT NOT NULL, merged INTEGER NOT NULL DEFAULT 0, branch_deleted INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)")
        self._connection.commit()

    def claim(self, delivery_id: str, action: str) -> bool:
        cursor = self._connection.execute("INSERT OR IGNORE INTO github_webhooks VALUES (?, ?, ?)", (delivery_id, action, datetime.now(timezone.utc).isoformat()))
        self._connection.commit()
        return cursor.rowcount == 1

    def reconcile(self, delivery_id: str, event: str, payload: dict) -> dict:
        """Apply a GitHub delivery once and return the resulting local state."""
        action = str(payload.get("action", event))
        if not self.claim(delivery_id, action):
            return {"duplicate": True, "delivery_id": delivery_id}
        pull_request = payload.get("pull_request") or {}
        number = payload.get("number") or pull_request.get("number")
        if number is None:
            return {"duplicate": False, "delivery_id": delivery_id, "ignored": True}
        merged = bool(pull_request.get("merged"))
        state = "merged" if merged else ("closed" if action == "closed" else "open")
        branch_deleted = bool(payload.get("deleted"))
        with self._connection:
            self._connection.execute("INSERT OR REPLACE INTO github_pull_requests VALUES (?, ?, ?, ?, ?)", (int(number), state, int(merged), int(branch_deleted), datetime.now(timezone.utc).isoformat()))
        return {"duplicate": False, "delivery_id": delivery_id, "number": int(number), "state": state, "merged": merged, "branch_deleted": branch_deleted}
