"""Inbound A2A: Agent Card + JSON-RPC endpoint backed by the durable jobs queue."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from core.a2a import protocol as p
from core.a2a.card import AGENT_CARD_PATH, build_extended_card, build_public_card
from core.a2a.config import A2AConfig, CallerConfig
from core.contracts import TaskContract
from core.jobs.repository import InvalidJobState

MAX_BODY_BYTES = 1_000_000
_DEFAULT_THRESHOLD = 0.65


def _extract_call(message: dict) -> tuple[str, dict]:
    for part in message.get("parts") or []:
        data = part.get("data") if isinstance(part, dict) else None
        if isinstance(data, dict) and isinstance(data.get("skill"), str):
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                raise p.invalid_params("data.payload must be an object")
            return data["skill"], payload
    raise p.invalid_params('message needs a data part {"skill": "...", "payload": {...}}')


def _threshold(message: dict) -> float:
    metadata = message.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise p.invalid_params("message.metadata must be an object")
    value = metadata.get("confidenceThreshold", _DEFAULT_THRESHOLD)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
        raise p.invalid_params("confidenceThreshold must be a number between 0 and 1")
    return float(value)


def _artifact(result: dict) -> dict:
    return {
        "artifactId": "result",
        "name": "result",
        "parts": [
            {
                "data": {
                    "result": result.get("result"),
                    "summary": result.get("summary") or "",
                    "gaps": result.get("gaps") or [],
                }
            }
        ],
        "metadata": {"confidence": result.get("confidence")},
    }


def _map_job(job, result: dict | None) -> tuple[str, str | None, list[dict]]:
    status = job.status.value
    if status == "queued":
        return p.STATE_SUBMITTED, None, []
    if status == "running":
        return p.STATE_WORKING, None, []
    if status == "cancelled":
        return p.STATE_CANCELED, None, []
    if status == "failed":
        return p.STATE_FAILED, "task failed", []
    outcome = (result or {}).get("status")
    if outcome == "complete":
        return p.STATE_COMPLETED, None, [_artifact(result)]
    if outcome == "escalated":
        return p.STATE_INPUT_REQUIRED, "awaiting human review", []
    if outcome == "no_agent_found" and result.get("failure_reason") == "origin_not_allowed":
        return p.STATE_REJECTED, "origin not allowed for this skill", []
    return p.STATE_FAILED, str((result or {}).get("failure_reason") or outcome or "task failed"), []


def _task_view(repo, job) -> dict:
    state, text, artifacts = _map_job(job, repo.get_result(job.job_id))
    return p.make_task(str(job.job_id), state, message_text=text, artifacts=artifacts)


def _parse(raw: bytes) -> tuple[object, str, dict, p.A2AError | None]:
    try:
        body = json.loads(raw)
    except ValueError:
        return None, "", {}, p.parse_error()
    if not isinstance(body, dict):
        return None, "", {}, p.invalid_request()
    request_id = body.get("id")
    method = body.get("method")
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return request_id, "", {}, p.invalid_request()
    params = body.get("params", {})
    if not isinstance(params, dict):
        return request_id, method, {}, p.invalid_params("params must be an object")
    return request_id, method, params, None


def build_a2a_router(
    *,
    config_getter: Callable[[], A2AConfig],
    registry_getter: Callable[[], object],
    jobs_getter: Callable[[], object],
    stream_poll_s: float = 0.5,
    stream_timeout_s: float = 300.0,
) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    def base_url(request: Request) -> str:
        return (os.getenv("A2A_PUBLIC_URL") or str(request.base_url)).rstrip("/")

    def enqueue(params: dict, caller: CallerConfig) -> tuple[UUID | None, dict]:
        message = params.get("message")
        if not isinstance(message, dict):
            raise p.invalid_params("params.message is required")
        message_id = message.get("messageId")
        if not isinstance(message_id, str) or not message_id.strip():
            raise p.invalid_params("message.messageId is required")
        if message.get("role") != p.ROLE_USER:
            raise p.invalid_params("message.role must be ROLE_USER")
        skill, payload = _extract_call(message)
        threshold = _threshold(message)
        if not caller.allows_skill(skill):
            return None, p.make_task(
                str(uuid.uuid4()), p.STATE_REJECTED, message_text="skill not permitted for this caller"
            )
        try:
            task = TaskContract(
                task_id=uuid.uuid4(),
                origin=caller.origin,  # always the token's origin, never the message's
                skill=skill,
                payload=payload,
                confidence_threshold=threshold,
            )
        except ValueError:
            raise p.invalid_params("invalid skill") from None
        repo = jobs_getter()
        job = repo.enqueue(
            task_id=task.task_id,
            task=task,
            idempotency_key=f"a2a:{caller.origin}:{message_id.strip()}",
        )
        return job.job_id, _task_view(repo, job)

    def owned_job(params: dict, caller: CallerConfig):
        repo = jobs_getter()
        try:
            job_id = UUID(str(params.get("id")))
        except ValueError:
            raise p.task_not_found() from None
        job = repo.get_job(job_id)
        task = repo.get_task(job_id) if job is not None else None
        if job is None or task is None or task.origin != caller.origin:
            raise p.task_not_found()
        return job

    def cancel(params: dict, caller: CallerConfig) -> dict:
        job = owned_job(params, caller)
        repo = jobs_getter()
        try:
            job = repo.cancel(job_id=job.job_id)
        except KeyError:
            raise p.task_not_found() from None
        except (ValueError, InvalidJobState):
            raise p.task_not_cancelable() from None
        return _task_view(repo, job)

    def dispatch(method: str, params: dict, caller: CallerConfig, base: str) -> dict:
        if method == "SendMessage":
            _, view = enqueue(params, caller)
            return {"task": view}
        if method == "GetTask":
            return _task_view(jobs_getter(), owned_job(params, caller))
        if method == "CancelTask":
            return cancel(params, caller)
        if method == "GetExtendedAgentCard":
            return build_extended_card(registry_getter(), base, caller)
        raise p.unsupported_operation()

    def events(request_id, job_id: UUID | None, first_view: dict):
        def frame(payload: dict) -> str:
            return f"data: {json.dumps(p.rpc_result(request_id, payload))}\n\n"

        yield frame({"task": first_view})
        if job_id is None:
            return
        repo = jobs_getter()
        state = first_view["status"]["state"]
        deadline = time.monotonic() + stream_timeout_s
        while state not in p.STOP_STATES and time.monotonic() < deadline:
            time.sleep(stream_poll_s)
            job = repo.get_job(job_id)
            if job is None:
                return
            view = _task_view(repo, job)
            new_state = view["status"]["state"]
            if new_state == state:
                continue
            state = new_state
            if state == p.STATE_COMPLETED:
                for artifact in view.get("artifacts", []):
                    yield frame(
                        {"artifactUpdate": {"taskId": view["id"], "contextId": view["contextId"], "artifact": artifact}}
                    )
            yield frame(
                {"statusUpdate": {"taskId": view["id"], "contextId": view["contextId"], "status": view["status"]}}
            )

    @router.get(AGENT_CARD_PATH)
    def public_card(request: Request):
        return build_public_card(registry_getter(), base_url(request))

    @router.post("/a2a")
    async def a2a(request: Request):
        caller = config_getter().authenticate(request.headers.get("Authorization", ""))
        if caller is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(p.rpc_error(None, p.invalid_request("Request too large")))
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(p.rpc_error(None, p.invalid_request("Request too large")))
        request_id, method, params, error = _parse(raw)
        if error is not None:
            return JSONResponse(p.rpc_error(request_id, error))
        if request.headers.get("A2A-Version") != p.A2A_VERSION:
            return JSONResponse(p.rpc_error(request_id, p.version_not_supported()))
        try:
            if method == "SendStreamingMessage":
                job_id, view = await run_in_threadpool(enqueue, params, caller)
                return StreamingResponse(events(request_id, job_id, view), media_type="text/event-stream")
            result = await run_in_threadpool(dispatch, method, params, caller, base_url(request))
        except p.A2AError as exc:
            return JSONResponse(p.rpc_error(request_id, exc))
        return JSONResponse(p.rpc_result(request_id, result))

    return router
