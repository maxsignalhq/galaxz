import httpx

from core.github import GitHubClient, PullRequestEvidence, WebhookStore, build_pr_body


def test_pr_body_contains_all_execution_evidence():
    body = build_pr_body(PullRequestEvidence("goal", ["task"], ["a.py"], "12/12 passed", "approved"))
    assert "goal" in body and "task" in body and "a.py" in body and "approved" in body


def test_github_client_posts_pr_and_check_without_logging_token():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"id": 1}, request=request)
    client = GitHubClient("token-value", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"))
    evidence = PullRequestEvidence("goal", [], [], "passed", "approved")
    assert client.create_pull_request("owner", "repo", head="branch", base="main", title="Goal", evidence=evidence)["id"] == 1
    assert client.create_check_run("owner", "repo", head_sha="a" * 40, name="tests", passed=True, summary="ok")["id"] == 1
    assert requests[0].headers["Authorization"] == "Bearer token-value"
    assert "token-value" not in requests[0].content.decode()


def test_webhook_delivery_is_idempotent(tmp_path):
    store = WebhookStore(tmp_path / "webhooks.db")
    assert store.claim("delivery-1", "opened")
    assert not store.claim("delivery-1", "opened")
