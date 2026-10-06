import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.a2a.agent import WormholeAgent
from core.a2a.client import A2AClient
from core.a2a.config import A2AConfig, AgentConfig, CallerConfig
from core.a2a.server import build_a2a_router
from core.contracts import SkillDefinition, SkillManifest
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry


def _work_one_job(jobs, result):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        claimed = jobs.claim(worker_id="remote-worker", lease_seconds=30)
        if claimed:
            job, attempt = claimed
            jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
            return
        time.sleep(0.02)


def test_wormhole_calls_a_remote_galaxz_over_a2a(tmp_path):
    # "Remote" Galaxz: Pulsar + inbound router + a stand-in durable worker.
    remote_registry = PulsarRegistry(db_path=str(tmp_path / "remote-pulsar.db"))
    remote_registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[SkillDefinition(skill_id="rigel.skill.echo", description="echo", input_schema={}, output_schema={})],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "remote-jobs.db")
    config = A2AConfig(callers=(CallerConfig("secret-token", "a2a:local-galaxz"),))
    remote = FastAPI()
    remote.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: remote_registry,
            jobs_getter=lambda: jobs,
            stream_poll_s=0.01,
        )
    )
    remote_http = TestClient(remote, base_url="https://remote.example")

    def client_factory(url, *, token, timeout_s):
        return A2AClient(url, token=token, timeout_s=timeout_s, poll_s=0.02, http=remote_http)

    # "Local" Galaxz: Wormhole pulls the remote card and registers its skills.
    local_registry = PulsarRegistry(db_path=str(tmp_path / "local-pulsar.db"))
    agent = WormholeAgent(
        local_registry,
        [AgentConfig(name="remote", url="https://remote.example", token="secret-token", timeout_s=5.0)],
        client_factory=client_factory,
    )
    assert agent.skill_ids == {"wormhole.remote.rigel.skill.echo"}

    threading.Timer(
        0.1, _work_one_job, args=(jobs, {"status": "complete", "confidence": 0.9, "result": {"echo": "hi"}, "summary": "hi"})
    ).start()
    out = agent.run("wormhole.remote.rigel.skill.echo", {"text": "hi"}, {})

    assert out["confidence"] == 1.0
    assert out["state"] == "TASK_STATE_COMPLETED"
    assert out["data"] == [{"result": {"echo": "hi"}, "summary": "hi", "gaps": []}]
    stored = jobs.list_jobs()[0]
    assert jobs.get_task(stored.job_id).origin == "a2a:local-galaxz"
    assert jobs.get_task(stored.job_id).skill == "rigel.skill.echo"


def _remote_with_restricted_skill(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "remote-pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[
                SkillDefinition(skill_id="open.skill", description="open", input_schema={}, output_schema={}),
                SkillDefinition(
                    skill_id="partner.skill",
                    description="only for the local galaxz",
                    input_schema={},
                    output_schema={},
                    allowed_origins=["a2a:local-galaxz"],
                ),
            ],
        )
    )
    config = A2AConfig(callers=(CallerConfig("right-token", "a2a:local-galaxz"),))
    app = FastAPI()
    app.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: registry,
            jobs_getter=lambda: SqliteJobRepository(tmp_path / "remote-jobs.db"),
        )
    )
    return TestClient(app, base_url="https://remote.example")


def _wormhole_for(tmp_path, http, token):
    registry = PulsarRegistry(db_path=str(tmp_path / f"local-{token}.db"))
    agent = WormholeAgent(
        registry,
        [AgentConfig(name="remote", url="https://remote.example", token=token)],
        client_factory=lambda url, *, token, timeout_s: A2AClient(url, token=token, http=http),
    )
    return agent


def test_authenticated_wormhole_discovers_skills_restricted_to_it(tmp_path):
    http = _remote_with_restricted_skill(tmp_path)
    agent = _wormhole_for(tmp_path, http, "right-token")
    assert agent.skill_ids == {"wormhole.remote.open.skill", "wormhole.remote.partner.skill"}


def test_wormhole_with_wrong_token_only_sees_the_public_skills(tmp_path):
    http = _remote_with_restricted_skill(tmp_path)
    agent = _wormhole_for(tmp_path, http, "wrong-token")
    assert agent.skill_ids == {"wormhole.remote.open.skill"}


def test_wormhole_without_a_token_only_sees_the_public_skills(tmp_path):
    http = _remote_with_restricted_skill(tmp_path)
    agent = _wormhole_for(tmp_path, http, None)
    assert agent.skill_ids == {"wormhole.remote.open.skill"}
