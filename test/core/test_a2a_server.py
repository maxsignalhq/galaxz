from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.a2a.config import A2AConfig, CallerConfig
from core.a2a.server import MAX_BODY_BYTES, build_a2a_router
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry

SKILL = "rigel.skill.code_generation"


def _skill(skill_id, allowed_origins=None):
    return SkillDefinition(
        skill_id=skill_id, description=skill_id, input_schema={}, output_schema={}, allowed_origins=allowed_origins
    )


@pytest.fixture
def env(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[_skill(SKILL), _skill("secret.skill", ["goal:*"]), _skill("partner.skill", ["a2a:alpha"])],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    config = A2AConfig(
        callers=(
            CallerConfig("tok-a", "a2a:alpha"),
            CallerConfig("tok-b", "a2a:beta", skills=("rigel.*",)),
        )
    )
    app = FastAPI()
    app.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: registry,
            jobs_getter=lambda: jobs,
            stream_poll_s=0.01,
            stream_timeout_s=2.0,
        )
    )
    return SimpleNamespace(client=TestClient(app), jobs=jobs, registry=registry)


def rpc(env, method, params=None, *, token="tok-a", version="1.0", raw=None, headers=None):
    hdrs = dict(headers or {})
    if version:
        hdrs["A2A-Version"] = version
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if raw is not None:
        return env.client.post("/a2a", content=raw, headers=hdrs)
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params if params is not None else {}}
    return env.client.post("/a2a", json=body, headers=hdrs)


def send_params(skill=SKILL, message_id="m1", payload=None, **message_extra):
    return {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"data": {"skill": skill, "payload": payload if payload is not None else {"spec": "x"}}}],
            **message_extra,
        }
    }


def send(env, token="tok-a", **kwargs):
    resp = rpc(env, "SendMessage", send_params(**kwargs), token=token)
    return resp.json()["result"]["task"]


def finish(env, result):
    claimed = env.jobs.claim(worker_id="w1", lease_seconds=30)
    assert claimed is not None
    job, attempt = claimed
    env.jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
    return job


def error_code(resp):
    return resp.json()["error"]["code"]


# ---- card ----------------------------------------------------------------


def test_public_card_hides_restricted_skills(env):
    card = env.client.get("/.well-known/agent-card.json").json()
    assert [s["id"] for s in card["skills"]] == [SKILL]
    assert card["supportedInterfaces"][0]["url"] == "http://testserver/a2a"


def test_public_card_honours_public_url_override(env, monkeypatch):
    monkeypatch.setenv("A2A_PUBLIC_URL", "https://galaxz.example/")
    card = env.client.get("/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["url"] == "https://galaxz.example/a2a"


def test_extended_card_per_caller(env):
    alpha = rpc(env, "GetExtendedAgentCard", token="tok-a").json()["result"]
    assert [s["id"] for s in alpha["skills"]] == ["partner.skill", SKILL]
    beta = rpc(env, "GetExtendedAgentCard", token="tok-b").json()["result"]
    assert [s["id"] for s in beta["skills"]] == [SKILL]


# ---- auth and envelope ---------------------------------------------------


def test_missing_or_bad_token_is_401(env):
    assert rpc(env, "GetTask", token=None).status_code == 401
    bad = rpc(env, "GetTask", token="nope")
    assert bad.status_code == 401
    assert bad.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("version", [None, "0.3", "2.0"])
def test_wrong_version_is_rejected(env, version):
    assert error_code(rpc(env, "SendMessage", send_params(), version=version)) == -32055


def test_malformed_json_is_parse_error(env):
    assert error_code(rpc(env, "", raw=b"{not json")) == -32700


def test_non_object_and_bad_envelope_are_invalid_request(env):
    assert error_code(rpc(env, "", raw=b"[1,2]")) == -32600
    assert error_code(rpc(env, "", raw=b'{"jsonrpc":"1.0","method":"GetTask"}')) == -32600
    assert error_code(rpc(env, "", raw=b'{"jsonrpc":"2.0","method":5}')) == -32600


def test_non_object_params_are_invalid_params(env):
    raw = b'{"jsonrpc":"2.0","id":1,"method":"GetTask","params":[1]}'
    assert error_code(rpc(env, "", raw=raw)) == -32602


def test_oversized_body_is_rejected_without_500(env):
    resp = rpc(env, "", raw=b"x" * (MAX_BODY_BYTES + 1))
    assert resp.status_code == 200
    assert error_code(resp) == -32600


def test_unknown_method_is_unsupported_operation(env):
    assert error_code(rpc(env, "ListTasks")) == -32052


def test_response_echoes_request_id(env):
    body = {"jsonrpc": "2.0", "id": "abc", "method": "GetExtendedAgentCard", "params": {}}
    resp = env.client.post("/a2a", json=body, headers={"A2A-Version": "1.0", "Authorization": "Bearer tok-a"})
    assert resp.json()["id"] == "abc"


# ---- SendMessage ---------------------------------------------------------


def test_send_message_enqueues_task_with_token_origin(env):
    task = send(env, metadata={"origin": "goal:evil"})
    assert task["status"]["state"] == "TASK_STATE_SUBMITTED"
    stored = env.jobs.get_task(__import__("uuid").UUID(task["id"]))
    assert isinstance(stored, TaskContract)
    assert stored.origin == "a2a:alpha"
    assert stored.skill == SKILL
    assert stored.payload == {"spec": "x"}
    assert stored.confidence_threshold == 0.65


def test_send_message_confidence_threshold_from_metadata(env):
    task = send(env, message_id="m2", metadata={"confidenceThreshold": 0.9})
    stored = env.jobs.get_task(__import__("uuid").UUID(task["id"]))
    assert stored.confidence_threshold == 0.9


def test_send_message_is_idempotent_per_origin_and_message_id(env):
    first = send(env, message_id="same")
    again = send(env, message_id="same")
    other_message = send(env, message_id="different")
    other_caller = send(env, token="tok-b", message_id="same")
    assert first["id"] == again["id"]
    assert len({first["id"], other_message["id"], other_caller["id"]}) == 3


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"message": "text"},
        {"message": {"role": "ROLE_USER", "parts": [{"data": {"skill": SKILL}}]}},
        {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"data": {"skill": SKILL}}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "hi"}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"skill": SKILL, "payload": "x"}}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"skill": "  "}}]}},
    ],
)
def test_send_message_invalid_params(env, params):
    assert error_code(rpc(env, "SendMessage", params)) == -32602


@pytest.mark.parametrize("threshold", [True, 1.5, -0.1, "high"])
def test_send_message_bad_threshold(env, threshold):
    resp = rpc(env, "SendMessage", send_params(metadata={"confidenceThreshold": threshold}))
    assert error_code(resp) == -32602


def test_caller_skill_allow_list_yields_rejected_task(env):
    task = send(env, token="tok-b", skill="partner.skill", message_id="r1")
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert env.jobs.list_jobs() == []  # nothing was enqueued
    assert error_code(rpc(env, "GetTask", {"id": task["id"]}, token="tok-b")) == -32050


# ---- GetTask state mapping ----------------------------------------------


def get_task(env, task_id, token="tok-a"):
    return rpc(env, "GetTask", {"id": task_id}, token=token).json()["result"]


def test_queued_and_running_states(env):
    task = send(env)
    assert get_task(env, task["id"])["status"]["state"] == "TASK_STATE_SUBMITTED"
    env.jobs.claim(worker_id="w1", lease_seconds=30)
    assert get_task(env, task["id"])["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.parametrize(
    "result,state",
    [
        ({"status": "complete", "confidence": 0.9, "result": {"code": "x"}, "summary": "s"}, "TASK_STATE_COMPLETED"),
        ({"status": "escalated", "confidence": 0.1}, "TASK_STATE_INPUT_REQUIRED"),
        ({"status": "no_agent_found", "failure_reason": "origin_not_allowed"}, "TASK_STATE_REJECTED"),
        ({"status": "no_agent_found", "failure_reason": "no_skill_match"}, "TASK_STATE_FAILED"),
        ({"status": "failed"}, "TASK_STATE_FAILED"),
    ],
)
def test_completed_job_result_maps_to_task_state(env, result, state):
    task = send(env)
    finish(env, result)
    assert get_task(env, task["id"])["status"]["state"] == state


def test_completed_task_carries_output_artifact_with_confidence(env):
    task = send(env)
    finish(env, {"status": "complete", "confidence": 0.9, "result": {"code": "x"}, "summary": "s", "gaps": ["g"]})
    done = get_task(env, task["id"])
    artifact = done["artifacts"][0]
    assert artifact["parts"] == [{"data": {"result": {"code": "x"}, "summary": "s", "gaps": ["g"]}}]
    assert artifact["metadata"] == {"confidence": 0.9}


def test_failed_job_does_not_leak_internal_error(env):
    task = send(env)
    job, attempt = env.jobs.claim(worker_id="w1", lease_seconds=30)
    env.jobs.record_failure(
        job_id=job.job_id, lease_token=attempt.lease_token, error="boom /srv/secret", error_code="permanent", retryable=False
    )
    view = get_task(env, task["id"])
    assert view["status"]["state"] == "TASK_STATE_FAILED"
    assert "boom" not in str(view) and "secret" not in str(view)


# ---- ownership -----------------------------------------------------------


def test_get_task_is_scoped_to_the_creating_caller(env):
    task = send(env, token="tok-a")
    assert error_code(rpc(env, "GetTask", {"id": task["id"]}, token="tok-b")) == -32050


def test_get_task_hides_jobs_not_created_over_a2a(env):
    foreign = TaskContract(origin="andromeda_api", skill=SKILL, payload={}, confidence_threshold=0.65)
    job = env.jobs.enqueue(task_id=foreign.task_id, task=foreign, idempotency_key="foreign-1")
    assert error_code(rpc(env, "GetTask", {"id": str(job.job_id)})) == -32050


@pytest.mark.parametrize("task_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000", None, 5])
def test_get_task_unknown_ids(env, task_id):
    assert error_code(rpc(env, "GetTask", {"id": task_id})) == -32050


# ---- CancelTask ----------------------------------------------------------


def test_cancel_task_and_idempotent_repeat(env):
    task = send(env)
    first = rpc(env, "CancelTask", {"id": task["id"]}).json()["result"]
    assert first["status"]["state"] == "TASK_STATE_CANCELED"
    again = rpc(env, "CancelTask", {"id": task["id"]}).json()["result"]
    assert again["status"]["state"] == "TASK_STATE_CANCELED"


def test_cancel_terminal_task_is_not_cancelable(env):
    task = send(env)
    finish(env, {"status": "complete"})
    assert error_code(rpc(env, "CancelTask", {"id": task["id"]})) == -32051


def test_cancel_other_callers_task_is_not_found(env):
    task = send(env, token="tok-a")
    assert error_code(rpc(env, "CancelTask", {"id": task["id"]}, token="tok-b")) == -32050


import json
import threading
import time


def _frames(response):
    out = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):])["result"])
    return out


def _finish_soon(env, result, delay=0.15):
    def run():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            claimed = env.jobs.claim(worker_id="w-stream", lease_seconds=30)
            if claimed:
                job, attempt = claimed
                env.jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
                return
            time.sleep(0.02)

    threading.Timer(delay, run).start()


def _stream(env, params, token="tok-a"):
    body = {"jsonrpc": "2.0", "id": 9, "method": "SendStreamingMessage", "params": params}
    headers = {"A2A-Version": "1.0", "Authorization": f"Bearer {token}"}
    return env.client.stream("POST", "/a2a", json=body, headers=headers)


def test_stream_emits_task_then_artifact_then_completed(env):
    _finish_soon(env, {"status": "complete", "confidence": 0.8, "result": {"code": "x"}, "summary": "s"})
    with _stream(env, send_params(message_id="s1")) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = _frames(resp)
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    kinds = [next(iter(f)) for f in frames[1:]]
    assert kinds[-2:] == ["artifactUpdate", "statusUpdate"]
    final = frames[-1]["statusUpdate"]
    assert final["status"]["state"] == "TASK_STATE_COMPLETED"
    assert final["taskId"] == frames[0]["task"]["id"]
    assert frames[-2]["artifactUpdate"]["artifact"]["metadata"] == {"confidence": 0.8}


def test_stream_ends_on_input_required(env):
    _finish_soon(env, {"status": "escalated"})
    with _stream(env, send_params(message_id="s2")) as resp:
        frames = _frames(resp)
    assert frames[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


def test_stream_for_rejected_skill_is_a_single_task_event(env):
    with _stream(env, send_params(skill="partner.skill", message_id="s3"), token="tok-b") as resp:
        frames = _frames(resp)
    assert len(frames) == 1
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_REJECTED"


def test_stream_validation_errors_are_plain_json_rpc_errors(env):
    with _stream(env, {"message": {}}) as resp:
        assert resp.headers["content-type"].startswith("application/json")
        resp.read()
        assert resp.json()["error"]["code"] == -32602


def test_stream_stops_at_timeout_when_job_never_finishes(env):
    with _stream(env, send_params(message_id="s4")) as resp:
        frames = _frames(resp)  # stream_timeout_s is 2.0 in the fixture
    assert len(frames) == 1
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
