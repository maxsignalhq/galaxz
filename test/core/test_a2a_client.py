import json

import httpx
import pytest

from core.a2a.client import A2AClient, A2AClientError

BASE = "https://remote.example"
RPC = f"{BASE}/a2a"


def card(**interface):
    iface = {"url": RPC, "protocolBinding": "JSONRPC", "protocolVersion": "1.0", **interface}
    return {"name": "Remote", "skills": [{"id": "translate", "description": "Translate"}], "supportedInterfaces": [iface]}


def task(state, *, text=None, data=None):
    out = {"id": "t-1", "contextId": "t-1", "status": {"state": state}}
    if text:
        out["status"]["message"] = {"messageId": "x", "role": "ROLE_AGENT", "parts": [{"text": text}]}
    if data is not None:
        out["artifacts"] = [{"artifactId": "a", "parts": [{"data": data}]}]
    return out


class Remote:
    """Scriptable fake A2A agent served through httpx.MockTransport."""

    def __init__(self, card_body=None, send=None, gets=(), extended=None):
        self.card_body = card_body if card_body is not None else card()
        self.send = send
        self.gets = list(gets)
        self.extended = extended
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=self.card_body)
        body = json.loads(request.content)
        method = body["method"]
        if method == "SendMessage":
            return self._reply(body, self.send)
        if method == "GetTask":
            return self._reply(body, self.gets.pop(0) if len(self.gets) > 1 else self.gets[0])
        if method == "GetExtendedAgentCard":
            return self._reply(body, self.extended) if self.extended is not None else httpx.Response(404)
        if method == "CancelTask":
            return self._reply(body, {"task": task("TASK_STATE_CANCELED")})
        return httpx.Response(404)

    @staticmethod
    def _reply(body, result):
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def methods(self):
        return [json.loads(r.content)["method"] for r in self.requests if r.method == "POST"]


def client_for(remote, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(remote))
    return A2AClient(BASE, http=http, poll_s=0.01, **kwargs)


def test_connect_picks_jsonrpc_v1_interface():
    c = client_for(Remote())
    assert c.connect()["name"] == "Remote"


def test_connect_accepts_binding_alias():
    client_for(Remote(card_body=card(protocolBinding="JSON-RPC"))).connect()


@pytest.mark.parametrize(
    "interface",
    [{"protocolVersion": "0.3"}, {"protocolBinding": "GRPC"}, {"url": "ftp://remote.example/a2a"}],
)
def test_connect_rejects_unusable_interfaces(interface):
    with pytest.raises(A2AClientError, match="JSON-RPC 1.0"):
        client_for(Remote(card_body=card(**interface))).connect()


def test_connect_refuses_interface_on_another_host_so_token_cannot_leak():
    remote = Remote(card_body=card(url="https://evil.example/a2a"))
    with pytest.raises(A2AClientError, match="JSON-RPC 1.0"):
        client_for(remote, token="secret").connect()
    assert all("evil.example" not in str(r.url) for r in remote.requests)


def test_connect_failures_become_client_errors():
    def boom(request):
        raise httpx.ConnectError("refused")

    c = A2AClient(BASE, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(A2AClientError, match="agent card"):
        c.connect()
    c2 = client_for(Remote(card_body=[1, 2]))
    with pytest.raises(A2AClientError, match="agent card"):
        c2.connect()


def test_execute_sends_text_and_data_parts_with_headers():
    remote = Remote(send={"task": task("TASK_STATE_COMPLETED", data={"out": 1})})
    c = client_for(remote, token="tok")
    result = c.execute("translate", {"text": "hello", "n": 2})
    rpc = [r for r in remote.requests if r.method == "POST"][0]
    assert rpc.headers["A2A-Version"] == "1.0"
    assert rpc.headers["Authorization"] == "Bearer tok"
    message = json.loads(rpc.content)["params"]["message"]
    assert message["role"] == "ROLE_USER" and message["messageId"]
    assert message["parts"] == [
        {"text": "hello"},
        {"data": {"skill": "translate", "payload": {"text": "hello", "n": 2}}},
    ]
    assert result.state == "TASK_STATE_COMPLETED"
    assert result.data == [{"out": 1}]


def test_execute_without_token_sends_no_authorization_and_no_text_part():
    remote = Remote(send={"task": task("TASK_STATE_COMPLETED")})
    client_for(remote).execute("translate", {"n": 1})
    rpc = [r for r in remote.requests if r.method == "POST"][0]
    assert "Authorization" not in rpc.headers
    assert json.loads(rpc.content)["params"]["message"]["parts"] == [
        {"data": {"skill": "translate", "payload": {"n": 1}}}
    ]


def test_execute_accepts_unwrapped_task_and_message_only_results():
    unwrapped = Remote(send=task("TASK_STATE_COMPLETED", text="done"))
    assert client_for(unwrapped).execute("translate", {}).text == "done"
    message_only = Remote(send={"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "hi"}]}})
    result = client_for(message_only).execute("translate", {})
    assert (result.state, result.text) == ("TASK_STATE_COMPLETED", "hi")


def test_execute_polls_until_terminal():
    remote = Remote(
        send={"task": task("TASK_STATE_WORKING")},
        gets=[task("TASK_STATE_WORKING"), task("TASK_STATE_COMPLETED", text="finally")],
    )
    result = client_for(remote).execute("translate", {})
    assert result.state == "TASK_STATE_COMPLETED" and result.text == "finally"
    assert remote.methods() == ["SendMessage", "GetTask", "GetTask"]


@pytest.mark.parametrize("state", ["TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED", "TASK_STATE_FAILED"])
def test_execute_returns_on_interrupted_and_failed_states(state):
    result = client_for(Remote(send={"task": task(state)})).execute("translate", {})
    assert result.state == state


def test_execute_times_out_and_cancels_remote():
    remote = Remote(send={"task": task("TASK_STATE_WORKING")}, gets=[task("TASK_STATE_WORKING")])
    c = client_for(remote, timeout_s=0.05)
    with pytest.raises(A2AClientError, match="timed out"):
        c.execute("translate", {})
    assert remote.methods()[-1] == "CancelTask"


def test_rpc_error_http_error_and_bad_json_become_client_errors_without_secrets():
    rpc_error = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32052, "message": "nope"}}
    with pytest.raises(A2AClientError, match="-32052"):
        client_for(Remote(send=httpx.Response(200, json=rpc_error)), token="s3cret").execute("t", {})
    with pytest.raises(A2AClientError, match="HTTP 500") as exc:
        client_for(Remote(send=httpx.Response(500, text="leaked s3cret body")), token="s3cret").execute("t", {})
    assert "s3cret" not in str(exc.value)
    with pytest.raises(A2AClientError, match="invalid JSON"):
        client_for(Remote(send=httpx.Response(200, text="<html>"))).execute("t", {})


def test_malformed_task_is_a_client_error():
    with pytest.raises(A2AClientError, match="malformed"):
        client_for(Remote(send={"task": {"id": "t", "status": {}}})).execute("t", {})


def _card_with_extended(**capabilities):
    body = card()
    body["capabilities"] = {"extendedAgentCard": True, **capabilities}
    return body


def test_connect_uses_extended_card_skills_when_token_and_capability():
    extended = {"skills": [{"id": "translate"}, {"id": "private-skill"}]}
    remote = Remote(card_body=_card_with_extended(), extended=extended)
    result = client_for(remote, token="tok").connect()
    assert [s["id"] for s in result["skills"]] == ["translate", "private-skill"]
    assert "GetExtendedAgentCard" in remote.methods()


def test_connect_skips_extended_card_without_token_or_capability():
    remote = Remote(card_body=_card_with_extended(), extended={"skills": [{"id": "x"}]})
    assert [s["id"] for s in client_for(remote).connect()["skills"]] == ["translate"]  # no token
    assert "GetExtendedAgentCard" not in remote.methods()
    remote = Remote(card_body=card(), extended={"skills": [{"id": "x"}]})  # capability absent
    assert [s["id"] for s in client_for(remote, token="tok").connect()["skills"]] == ["translate"]
    assert "GetExtendedAgentCard" not in remote.methods()


def test_connect_falls_back_to_public_card_when_extended_card_is_refused():
    refused = httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32052, "message": "no"}})
    remote = Remote(card_body=_card_with_extended(), extended=refused)
    assert [s["id"] for s in client_for(remote, token="tok").connect()["skills"]] == ["translate"]
    malformed = Remote(card_body=_card_with_extended(), extended={"name": "no skills key"})
    assert [s["id"] for s in client_for(malformed, token="tok").connect()["skills"]] == ["translate"]
