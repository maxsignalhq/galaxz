from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import MAX_SKILL_LESSONS, NebulaStore
from core.pulsar.registry import PulsarRegistry

SKILL = "fake.skill.echo"


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
            skills=[SkillDefinition(skill_id=SKILL, description="echo", input_schema={}, output_schema={})],
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


def _route(andromeda, payload=None, origin="goal:1"):
    return andromeda.route(
        task=TaskContract(origin=origin, skill=SKILL, payload=payload or {"spec": "parse the config file"}, confidence_threshold=0.5)
    )


def test_skill_lessons_are_passed_even_without_keyword_overlap(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember(f"skill:{SKILL}", "Prefer fromisoformat for ISO dates.", tags=["lesson", "agent:fake"])
    assert _route(andromeda)["status"] == "complete"
    memory = agent.contexts[0]["memory"]
    assert [m["content"] for m in memory] == ["Prefer fromisoformat for ISO dates."]
    assert memory[0]["namespace"] == f"skill:{SKILL}"
    assert memory[0]["tags"] == ["lesson", "agent:fake"]


def test_lessons_apply_even_when_the_payload_has_no_text(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember(f"skill:{SKILL}", "Always validate input.")
    _route(andromeda, payload={"n": 3})
    assert [m["content"] for m in agent.contexts[0]["memory"]] == ["Always validate input."]


def test_other_skills_lessons_are_not_used(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("skill:vega.skill.something", "a lesson for another skill")
    _route(andromeda)
    assert "memory" not in agent.contexts[0]


def test_lessons_are_capped_newest_first(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    for i in range(MAX_SKILL_LESSONS + 3):
        nebula.remember(f"skill:{SKILL}", f"lesson number {i}")
    _route(andromeda)
    contents = [m["content"] for m in agent.contexts[0]["memory"]]
    assert contents == [f"lesson number {i}" for i in range(MAX_SKILL_LESSONS + 2, 2, -1)]


def test_lessons_combine_with_keyword_memory_without_duplicates(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("goal:1", "config files live in config/")
    nebula.remember(f"skill:{SKILL}", "Prefer yaml.safe_load for config files.")
    _route(andromeda)
    contents = [m["content"] for m in agent.contexts[0]["memory"]]
    assert sorted(contents) == ["Prefer yaml.safe_load for config files.", "config files live in config/"]
    ids = [m["memory_id"] for m in agent.contexts[0]["memory"]]
    assert len(ids) == len(set(ids))


def test_a_lesson_whose_namespace_matches_the_origin_is_not_duplicated(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember(f"skill:{SKILL}", "parse config carefully with yaml")
    _route(andromeda, origin=f"skill:{SKILL}")
    contents = [m["content"] for m in agent.contexts[0]["memory"]]
    assert contents == ["parse config carefully with yaml"]


def test_routing_is_unchanged_without_any_lessons(tmp_path):
    andromeda, agent, nebula = _setup(tmp_path)
    nebula.remember("goal:1", "unrelated lunch note")
    assert _route(andromeda)["status"] == "complete"
    assert "memory" not in agent.contexts[0]
