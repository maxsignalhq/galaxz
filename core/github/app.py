"""GitHub App authentication with least-privilege installation tokens."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx


REQUESTED_PERMISSIONS = {
    "metadata": "read",
    "contents": "write",
    "checks": "write",
    "pull_requests": "write",
}


class GitHubAppError(RuntimeError):
    """Raised when App authentication or installation access fails."""


class GitHubAppClient:
    """Exchange an App identity for ephemeral installation credentials.

    Neither the private key nor an installation token is written to disk. The
    installation token is retained only in this object until shortly before
    GitHub's reported expiration time.
    """

    def __init__(self, app_id: str, private_key: str, *, base_url: str = "https://api.github.com", client: httpx.Client | None = None):
        if not app_id.strip() or not private_key.strip():
            raise ValueError("GitHub App ID and private key are required")
        self.app_id = app_id
        self._private_key = private_key.replace("\\n", "\n")
        self._client = client or httpx.Client(base_url=base_url, timeout=20)
        self._installation_tokens: dict[int, tuple[str, float]] = {}

    def list_installations(self) -> list[dict]:
        return self._request("GET", "/app/installations", app_auth=True).json()

    def list_repositories(self, installation_id: int) -> list[dict]:
        token = self._installation_token(installation_id)
        response = self._request("GET", f"/installation/repositories", token=token)
        return response.json().get("repositories", [])

    def installation_token(self, installation_id: int) -> str:
        """Return an ephemeral token for use by a downstream GitHub client."""
        return self._installation_token(installation_id)

    def _installation_token(self, installation_id: int) -> str:
        cached = self._installation_tokens.get(installation_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        response = self._request("POST", f"/app/installations/{installation_id}/access_tokens", app_auth=True)
        payload = response.json()
        token = payload.get("token")
        expires_at = payload.get("expires_at")
        if not token or not expires_at:
            raise GitHubAppError("GitHub returned an invalid installation token")
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        self._installation_tokens[installation_id] = (token, expiry)
        return token

    def _request(self, method: str, path: str, *, app_auth: bool = False, token: str | None = None) -> httpx.Response:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if app_auth:
            headers["Authorization"] = f"Bearer {self._app_jwt()}"
        elif token:
            headers["Authorization"] = f"Bearer {token}"
        response = self._client.request(method, path, headers=headers)
        if response.status_code in (401, 403):
            raise GitHubAppError("GitHub App installation is unavailable or revoked")
        response.raise_for_status()
        return response

    def _app_jwt(self) -> str:
        try:
            import jwt
        except ImportError as exc:
            raise GitHubAppError("PyJWT[crypto] is required for GitHub App authentication") from exc
        now = int(datetime.now(timezone.utc).timestamp())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self._private_key, algorithm="RS256")
