import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.task_log import TaskLog
from core.a2a.agent import WormholeAgent
from core.a2a.client import A2AClientError, RemoteResult
from core.a2a.config import AgentConfig
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import NebulaStore
from core.pulsar.registry import PulsarRegistry

CARD = {
    "skills": [
        {"id": "translate", "description": "Translate text"},
        {"id": "bad id!", "description": "invalid id is skipped"},
        {"id": "summarize"},
    ]
}


class FakeClient:
    instances: dict[str, "FakeClient"] = {}

    def __init__(self, url, *, token=None, timeout_s=60.0):
        self.url, self.token, self.timeout_s = url, token, timeout_s
        self.closed = False
        self.calls: list[tuple[str, dict]] = []
        self.card = CARD
        self.result = RemoteResult("TASK_STATE_COMPLETED", "bonjour", [{"out": "bonjour"}], {})
        FakeClient.instances[url] = self

    def connect(self):
        if self.card is None:
            raise A2AClientError("agent card fetch failed: ConnectError")
        return self.card

    def execute(self, skill, payload):
        self.calls.append((skill, payload))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset():
    FakeClient.instances.clear()


def cfg(name="translator", url="https://t.example", allowed=None):
    return AgentConfig(name=name, url=url, token="tok", timeout_s=7.0, allowed_origins=allowed)


def registry_for(tmp_path):
    return PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))


def test_registers_remote_skills_with_local_policy(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg(allowed=["goal:*"])], client_factory=FakeClient)
    manifest = registry.get_agent("wormhole")
    skills = {s.skill_id: s for s in manifest.skills}
    assert set(skills) == {"wormhole.translator.translate", "wormhole.translator.summarize"}
    assert skills["wormhole.translator.translate"].description == "Translate text"
    assert skills["wormhole.translator.summarize"].description == "summarize"
    assert skills["wormhole.translator.translate"].allowed_origins == ["goal:*"]
    assert agent.skill_ids == set(skills)
    client = FakeClient.instances["https://t.example"]
    assert (client.token, client.timeout_s) == ("tok", 7.0)


def test_unreachable_agent_is_skipped_and_reported(tmp_path):
    registry = registry_for(tmp_path)

    class DeadFactory(FakeClient):
        def __init__(self, url, **kw):
            super().__init__(url, **kw)
            if "dead" in url:
                self.card = None

    agent = WormholeAgent(
        registry, [cfg(), cfg(name="dead", url="https://dead.example")], client_factory=DeadFactory
    )
    status = agent.status()
    assert status["configured"] is True
    good, dead = status["agents"]
    assert good["ok"] is True and good["error"] is None
    assert [s["skill_id"] for s in good["skills"]] == [
        "wormhole.translator.translate",
        "wormhole.translator.summarize",
    ]
    assert dead["name"] == "dead" and dead["ok"] is False and "ConnectError" in dead["error"]
    assert dead["skills"] == []
    assert DeadFactory.instances["https://dead.example"].closed is True


def test_no_skills_means_no_manifest_and_stale_one_is_removed(tmp_path):
    registry = registry_for(tmp_path)
    registry.register(
        SkillManifest(
            agent_id="wormhole",
            agent_name="old",
            version="0",
            health_endpoint="http://wormhole:8000/health",
            skills=[SkillDefinition(skill_id="wormhole.old.x", description="x", input_schema={}, output_schema={})],
        )
    )
    empty = WormholeAgent(registry, [], client_factory=FakeClient)
    assert registry.get_agent("wormhole") is None
    assert empty.status() == {"configured": False, "agents": []}
    assert empty.skill_ids == set()
    assert PulsarRegistry(db_path=str(tmp_path / "pulsar.db")).get_agent("wormhole") is None


def test_run_maps_remote_state_to_binary_confidence(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    client = FakeClient.instances["https://t.example"]

    ok = agent.run("wormhole.translator.translate", {"text": "hello"}, {})
    assert client.calls == [("translate", {"text": "hello"})]
    assert ok["confidence"] == 1.0
    assert ok["summary"] == "bonjour"
    assert ok["state"] == "TASK_STATE_COMPLETED" and ok["data"] == [{"out": "bonjour"}]
    assert ok["gaps"] == [] and ok["artifacts"] == [] and ok["writable"] is False
    assert ok["execution_result"] is None and ok["externally_calibrated"] is False
    assert set(ok["confidence_breakdown"]) == {"structural", "self_critique", "historical"}

    for state in [
        "TASK_STATE_FAILED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_AUTH_REQUIRED",
    ]:
        client.result = RemoteResult(state, "why", [], {})
        bad = agent.run("wormhole.translator.translate", {}, {})
        assert bad["confidence"] == 0.0
        assert bad["gaps"] == ["why"]
        assert bad["state"] == state


def test_run_gap_has_fallback_text_and_unknown_skill_raises(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    FakeClient.instances["https://t.example"].result = RemoteResult("TASK_STATE_FAILED", "", [], {})
    assert agent.run("wormhole.translator.translate", {}, {})["gaps"] == ["remote task ended as TASK_STATE_FAILED"]
    with pytest.raises(ValueError, match="unknown skill"):
        agent.run("wormhole.translator.missing", {}, {})


def test_transport_error_propagates_so_the_task_fails(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    FakeClient.instances["https://t.example"].result = A2AClientError("timed out waiting for remote task")
    with pytest.raises(A2AClientError, match="timed out"):
        agent.run("wormhole.translator.translate", {}, {})


def test_close_closes_every_connected_client(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    agent.close()
    assert FakeClient.instances["https://t.example"].closed is True


def test_routes_through_andromeda_and_honors_origin_policy(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg(allowed=["ops"])], client_factory=FakeClient)
    andromeda = Andromeda(
        registry=registry,
        review_queue=ReviewQueue(db_path=str(tmp_path / "reviews.db")),
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"wormhole": agent},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        nebula=NebulaStore(db_path=str(tmp_path / "nebula.db")),
    )

    def route(origin):
        return andromeda.route(
            task=TaskContract(
                origin=origin,
                skill="wormhole.translator.translate",
                payload={"text": "hello"},
                confidence_threshold=0.9,
            )
        )

    assert route("ops")["status"] == "complete"
    assert route("intruder")["failure_reason"] == "origin_not_allowed"
    FakeClient.instances["https://t.example"].result = RemoteResult("TASK_STATE_FAILED", "no", [], {})
    assert route("ops")["status"] != "complete"
