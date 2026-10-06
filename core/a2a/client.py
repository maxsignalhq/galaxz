"""Synchronous A2A v1.0 client (JSON-RPC over HTTPS) for outbound calls."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from core.a2a import protocol as p
from core.a2a.card import AGENT_CARD_PATH

MAX_RESPONSE_BYTES = 5_000_000
_REQUEST_TIMEOUT_S = 30.0


class A2AClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteResult:
    state: str
    text: str
    data: list
    raw: dict


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()


def _parts_text(parts) -> list[str]:
    return [part["text"] for part in parts or [] if isinstance(part, dict) and isinstance(part.get("text"), str)]


def _task_state(task: dict) -> str:
    status = task.get("status")
    state = status.get("state") if isinstance(status, dict) else None
    if not isinstance(task.get("id"), str) or not isinstance(state, str):
        raise A2AClientError("remote returned a malformed task")
    return state


def _task_result(task: dict) -> RemoteResult:
    state = _task_state(task)
    texts: list[str] = []
    data: list = []
    message = task["status"].get("message")
    if isinstance(message, dict):
        texts += _parts_text(message.get("parts"))
    for artifact in task.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        texts += _parts_text(artifact.get("parts"))
        data += [part["data"] for part in artifact.get("parts") or [] if isinstance(part, dict) and "data" in part]
    return RemoteResult(state=state, text="\n".join(texts), data=data, raw=task)


class A2AClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_s: float = 60.0,
        poll_s: float = 0.5,
        http: httpx.Client | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._http = http or httpx.Client(timeout=_REQUEST_TIMEOUT_S)  # redirects are not followed
        self._owns_http = http is None
        self._rpc_url: str | None = None

    def _headers(self) -> dict:
        headers = {"A2A-Version": p.A2A_VERSION, "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def fetch_card(self) -> dict:
        try:
            resp = self._http.get(self._base + AGENT_CARD_PATH, headers=self._headers())
        except httpx.HTTPError as exc:
            raise A2AClientError(f"agent card fetch failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise A2AClientError(f"agent card fetch failed: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise A2AClientError("agent card fetch failed: invalid JSON") from None
        if not isinstance(body, dict):
            raise A2AClientError("agent card fetch failed: card is not an object")
        return body

    def _pick_interface(self, card: dict) -> str:
        for interface in card.get("supportedInterfaces") or []:
            if not isinstance(interface, dict):
                continue
            url = interface.get("url")
            if (
                interface.get("protocolBinding") in p.JSONRPC_BINDINGS
                and interface.get("protocolVersion") == p.A2A_VERSION
                and isinstance(url, str)
                and url.startswith(("http://", "https://"))
                # The card is remote-controlled: never send our token to another host.
                and _origin(url) == _origin(self._base)
            ):
                return url
        raise A2AClientError("agent has no JSON-RPC 1.0 interface on its own host")

    def connect(self) -> dict:
        card = self.fetch_card()
        self._rpc_url = self._pick_interface(card)
        capabilities = card.get("capabilities")
        if self._token and isinstance(capabilities, dict) and capabilities.get("extendedAgentCard") is True:
            # The public card only lists open skills; an authenticated caller may be
            # permitted more. Fall back to the public card if the remote refuses us.
            try:
                extended = self._call("GetExtendedAgentCard", {})
            except A2AClientError:
                return card
            if isinstance(extended.get("skills"), list):
                return {**card, "skills": extended["skills"]}
        return card

    def _call(self, method: str, params: dict) -> dict:
        assert self._rpc_url is not None
        body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        try:
            resp = self._http.post(self._rpc_url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise A2AClientError(f"{method} failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise A2AClientError(f"{method} failed: HTTP {resp.status_code}")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise A2AClientError(f"{method} failed: response too large")
        try:
            payload = resp.json()
        except ValueError:
            raise A2AClientError(f"{method} failed: invalid JSON") from None
        if not isinstance(payload, dict):
            raise A2AClientError(f"{method} failed: invalid response")
        error = payload.get("error")
        if isinstance(error, dict):
            raise A2AClientError(f"{method} failed: {error.get('code')} {str(error.get('message'))[:200]}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise A2AClientError(f"{method} failed: missing result")
        return result

    def _cancel_quietly(self, task_id: str) -> None:
        try:
            self._call("CancelTask", {"id": task_id})
        except A2AClientError:
            pass

    def execute(self, remote_skill: str, payload: dict) -> RemoteResult:
        if self._rpc_url is None:
            self.connect()
        deadline = time.monotonic() + self._timeout_s
        parts: list[dict] = []
        text = " ".join(v for v in payload.values() if isinstance(v, str)).strip()
        if text:
            parts.append({"text": text})
        parts.append({"data": {"skill": remote_skill, "payload": payload}})
        message = {"messageId": str(uuid.uuid4()), "role": p.ROLE_USER, "parts": parts}
        result = self._call("SendMessage", {"message": message})

        reply = result.get("message")
        if "task" not in result and isinstance(reply, dict):
            return RemoteResult(
                state=p.STATE_COMPLETED, text="\n".join(_parts_text(reply.get("parts"))), data=[], raw=reply
            )
        task = result.get("task", result)  # tolerate an unwrapped Task
        while True:
            state = _task_state(task)
            if state in p.STOP_STATES:
                return _task_result(task)
            if time.monotonic() >= deadline:
                self._cancel_quietly(task["id"])
                raise A2AClientError("timed out waiting for remote task")
            time.sleep(self._poll_s)
            task = self._call("GetTask", {"id": task["id"]})

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
