"""A2A v1.0 wire primitives: task states, errors, JSON-RPC envelopes, Task builder."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

A2A_VERSION = "1.0"
BINDING = "JSONRPC"  # what we emit on our Agent Card
JSONRPC_BINDINGS = frozenset({"JSONRPC", "JSON-RPC"})  # what we accept on remote cards

STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
STATE_WORKING = "TASK_STATE_WORKING"
STATE_COMPLETED = "TASK_STATE_COMPLETED"
STATE_FAILED = "TASK_STATE_FAILED"
STATE_CANCELED = "TASK_STATE_CANCELED"
STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
STATE_REJECTED = "TASK_STATE_REJECTED"
STATE_AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_CANCELED, STATE_REJECTED})
# Nothing more happens on a task in these states without a client action.
STOP_STATES = TERMINAL_STATES | {STATE_INPUT_REQUIRED, STATE_AUTH_REQUIRED}

ROLE_USER = "ROLE_USER"
ROLE_AGENT = "ROLE_AGENT"

_ERROR_DOMAIN = "a2a-protocol.org"


class A2AError(Exception):
    def __init__(self, code: int, message: str, reason: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason


def parse_error() -> A2AError:
    return A2AError(-32700, "Parse error")


def invalid_request(detail: str = "Invalid request") -> A2AError:
    return A2AError(-32600, detail)


def invalid_params(detail: str) -> A2AError:
    return A2AError(-32602, detail, "INVALID_PARAMS")


def task_not_found() -> A2AError:
    return A2AError(-32050, "Task not found or not accessible", "TASK_NOT_FOUND")


def task_not_cancelable() -> A2AError:
    return A2AError(-32051, "Task is not in a cancelable state", "TASK_NOT_CANCELABLE")


def unsupported_operation() -> A2AError:
    return A2AError(-32052, "Operation not supported", "UNSUPPORTED_OPERATION")


def version_not_supported() -> A2AError:
    return A2AError(-32055, "Protocol version not supported", "VERSION_NOT_SUPPORTED")


def rpc_result(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id, error: A2AError) -> dict:
    body: dict = {"code": error.code, "message": error.message}
    if error.reason:
        body["data"] = {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": error.reason,
                    "domain": _ERROR_DOMAIN,
                }
            ]
        }
    return {"jsonrpc": "2.0", "id": request_id, "error": body}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_task(
    task_id: str,
    state: str,
    *,
    context_id: str | None = None,
    message_text: str | None = None,
    artifacts: list[dict] | None = None,
) -> dict:
    status: dict = {"state": state, "timestamp": _now()}
    if message_text:
        status["message"] = {
            "messageId": str(uuid.uuid4()),
            "role": ROLE_AGENT,
            "parts": [{"text": message_text}],
        }
    task: dict = {"id": task_id, "contextId": context_id or task_id, "status": status}
    if artifacts:
        task["artifacts"] = artifacts
    return task
