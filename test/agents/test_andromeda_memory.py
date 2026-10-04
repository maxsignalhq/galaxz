from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.skills.code_generation import code_generation
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import NebulaStore
from core.pulsar.registry import PulsarRegistry


class CapturingAgent:
    def __init__(self):
        self.contexts = []

    def run(self, skill_id, payload, context):
        self.contexts.append(context)
        return {"result": {"ok": True}, "confidence": 0.95}


def _setup(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="fake",
            agent_name="fake",
            version="1.0.0",
            skills=[SkillDefinition(skill_id="fake.skill.echo", description="echo", input_schema={}, output_schema={})],
            health_endpoint="/health",
        )
    )
    agent = CapturingAgent()
    nebula = NebulaStore(db_path=str(tmp_path / "nebula.db"))
    andromeda = Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"fake": agent},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        nebula=nebula,
    )
    return andromeda, agent, nebula


def _route(andromeda, origin="goal:1", payload=None):
    return andromeda.route(
        task=TaskContract(
            origin=origin,
            skill="fake.skill.echo",
            payload=payload or {"spec": "parse the config file"},
            confidence_threshold=0.5,
        )
    )


def test_memory_injected_from_origin_and_global(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("goal:1", "config files live in config/")
    nebula.remember("global", "always parse config with yaml.safe_load")
    nebula.remember("goal:2", "config of another goal")
    assert _route(andromeda)["status"] == "complete"
    memory = agent.contexts[0]["memory"]
    assert {m["content"] for m in memory} == {
        "config files live in config/",
        "always parse config with yaml.safe_load",
    }
    assert set(memory[0]) == {"memory_id", "namespace", "content", "tags"}


def test_no_memory_key_when_nothing_matches(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("goal:1", "completely unrelated lunch note")
    _route(andromeda)
    assert "memory" not in agent.contexts[0]


def test_memory_does_not_leak_into_task_payload(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("global", "parse config carefully")
    result = _route(andromeda)
    assert "memory" not in result["payload"]


def test_rigel_prompt_includes_memory_block():
    seen = {}

    def llm(system, user):
        seen["user"] = user
        return "x = 1"

    code_generation(
        {"spec": "parse config", "memory": [{"content": "use yaml.safe_load", "namespace": "global", "tags": []}]},
        llm,
    )
    assert "Relevant memory" in seen["user"]
    assert "use yaml.safe_load" in seen["user"]

    code_generation({"spec": "parse config"}, llm)
    assert "Relevant memory" not in seen["user"]
