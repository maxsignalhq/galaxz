import sys
from pathlib import Path

import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import TaskContract
from core.nebula.store import NebulaStore
from core.pulsar.registry import PulsarRegistry
from core.quasar.agent import QuasarAgent, load_mcp_config
from core.quasar.client import McpError, McpStdioClient

SERVER = [sys.executable, str(Path(__file__).parents[1] / "fixtures" / "fake_mcp_server.py")]


@pytest.fixture
def client():
    c = McpStdioClient(SERVER, timeout_s=5)
    yield c
    c.close()


def test_list_tools_follows_pagination(client):
    assert [t["name"] for t in client.list_tools()] == ["echo", "fail", "slow", "crash"]


def test_call_tool_returns_content(client):
    result = client.call_tool("echo", {"text": "hi"})
    assert result["content"][0]["text"] == "hi"
    assert result["isError"] is False


def test_jsonrpc_error_raises(client):
    with pytest.raises(McpError, match="unknown tool"):
        client.call_tool("nope", {})


def test_timeout_raises_and_client_recovers():
    c = McpStdioClient(SERVER, timeout_s=0.3)
    try:
        with pytest.raises(McpError, match="timed out"):
            c.call_tool("slow", {})
        c.close()  # kill the stuck server; next call must restart it
        assert c.call_tool("echo", {"text": "again"})["content"][0]["text"] == "again"
    finally:
        c.close()


def test_restarts_after_server_crash(client):
    with pytest.raises(McpError):
        client.call_tool("crash", {})
    assert client.call_tool("echo", {"text": "back"})["content"][0]["text"] == "back"


def test_missing_command_raises_mcp_error():
    with pytest.raises(McpError, match="failed to start"):
        McpStdioClient(["/nonexistent/binary"], timeout_s=1).list_tools()


def _servers(allowed_origins=None):
    return [
        {"name": "fake", "command": SERVER, "timeout_s": 5, "allowed_origins": allowed_origins}
    ]


def test_agent_registers_each_tool_as_a_skill(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = QuasarAgent(registry, _servers(["goal:*"]))
    try:
        manifest = registry.get_agent("quasar")
        ids = {s.skill_id for s in manifest.skills}
        assert ids == {"quasar.fake.echo", "quasar.fake.fail", "quasar.fake.slow", "quasar.fake.crash"}
        echo = next(s for s in manifest.skills if s.skill_id == "quasar.fake.echo")
        assert echo.input_schema["properties"]["text"]["type"] == "string"
        assert echo.allowed_origins == ["goal:*"]
    finally:
        agent.close()


def test_agent_skips_dead_server_and_registers_nothing(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = QuasarAgent(registry, [{"name": "dead", "command": ["/nonexistent/binary"], "timeout_s": 1}])
    assert registry.get_agent("quasar") is None
    assert agent.skill_ids == set()


def test_run_success_and_tool_error(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = QuasarAgent(registry, _servers())
    try:
        ok = agent.run("quasar.fake.echo", {"text": "hello"}, {})
        assert ok["confidence"] == 1.0
        assert ok["summary"] == "hello"
        bad = agent.run("quasar.fake.fail", {}, {})
        assert bad["confidence"] == 0.0
        assert bad["summary"] == "boom"
        with pytest.raises(ValueError, match="unknown skill"):
            agent.run("quasar.fake.missing", {}, {})
    finally:
        agent.close()


def test_routes_through_andromeda_and_honors_origin_policy(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = QuasarAgent(registry, _servers(["ops"]))
    try:
        andromeda = Andromeda(
            registry=registry,
            review_queue=ReviewQueue(db_path=str(tmp_path / "reviews.db")),
            task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
            agents={"quasar": agent},
            artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
            nebula=NebulaStore(db_path=str(tmp_path / "nebula.db")),
        )

        def route(origin, skill="quasar.fake.echo"):
            return andromeda.route(
                task=TaskContract(origin=origin, skill=skill, payload={"text": "routed"}, confidence_threshold=0.9)
            )

        allowed = route("ops")
        assert allowed["status"] == "complete"
        assert allowed["summary"] == "routed"
        assert route("intruder")["failure_reason"] == "origin_not_allowed"
        assert route("ops", "quasar.fake.fail")["status"] != "complete"
    finally:
        agent.close()


def test_load_mcp_config(tmp_path):
    cfg = tmp_path / "mcp.yaml"
    cfg.write_text("servers:\n  - name: fs\n    command: [npx, -y, server]\n")
    assert load_mcp_config(str(cfg)) == [{"name": "fs", "command": ["npx", "-y", "server"]}]
    assert load_mcp_config(str(tmp_path / "missing.yaml")) == []
    cfg.write_text("servers: []\n")
    assert load_mcp_config(str(cfg)) == []
