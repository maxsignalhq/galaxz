import httpx

from core.github import GitHubAppClient, GitHubAppError, REQUESTED_PERMISSIONS


def test_github_app_requests_only_required_permissions():
    assert REQUESTED_PERMISSIONS == {
        "metadata": "read",
        "contents": "write",
        "checks": "write",
        "pull_requests": "write",
    }


def test_installation_token_is_exchanged_and_cached_in_memory():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"token": "ephemeral", "expires_at": "2099-01-01T00:00:00Z"}, request=request)

    client = GitHubAppClient("123", "private-key", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"))
    client._app_jwt = lambda: "app-jwt"
    assert client.installation_token(42) == "ephemeral"
    assert client.installation_token(42) == "ephemeral"
    assert len(calls) == 1
    assert calls[0].url.path == "/app/installations/42/access_tokens"
    assert calls[0].headers["Authorization"] == "Bearer app-jwt"
    assert client._installation_tokens[42][0] == "ephemeral"


def test_revoked_installation_is_surfaced():
    def handler(request):
        return httpx.Response(403, json={"message": "Resource not accessible by integration"}, request=request)

    client = GitHubAppClient("123", "private-key", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"))
    client._app_jwt = lambda: "app-jwt"
    try:
        client.installation_token(42)
    except GitHubAppError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("revoked installation should fail closed")
