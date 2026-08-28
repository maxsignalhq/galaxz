import json
import pytest
from core.contracts import GoalContract, SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry
from agents.andromeda.planner import GoalPlanner, PlanValidationError


@pytest.fixture
def registry(tmp_path):
    r = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    r.register(SkillManifest(
        agent_id="rigel", agent_name="Rigel", version="1.0.0",
        skills=[
            SkillDefinition(skill_id="rigel.skill.code_generation", description="gen code", input_schema={}, output_schema={}),
            SkillDefinition(skill_id="rigel.skill.test_writing", description="write tests", input_schema={}, output_schema={}),
        ],
        health_endpoint="/health",
    ))
    return r


def _planner(registry, payload: dict):
    def fake_llm(messages, config, system_prompt=""):
        return json.dumps(payload), 0, 0
    return GoalPlanner(registry, llm=fake_llm, config_loader=lambda: object())


def _goal():
    return GoalContract(origin="test", objective="build a todo API with tests", confidence_threshold=0.65)


def test_plan_resolves_dependency_indices_to_uuids(registry):
    payload = {
        "plan_confidence": 0.8,
        "projects": [{
            "title": "API", "description": "",
            "tasks": [
                {"skill": "rigel.skill.code_generation", "payload": {"spec": "todo API"}, "depends_on": []},
                {"skill": "rigel.skill.test_writing", "payload": {"code": "..."}, "depends_on": [0]},
            ],
        }],
    }
    result = _planner(registry, payload).plan(_goal())
    assert result.plan_confidence == 0.8
    assert len(result.tasks) == 2
    assert result.tasks[1].depends_on == [result.tasks[0].task_id]
    assert result.tasks[0].goal_id == result.tasks[1].goal_id


def test_plan_rejects_unknown_skill(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "nope.skill.unknown", "payload": {}, "depends_on": []}]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_rejects_out_of_range_dependency(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": [5]}]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_rejects_cycle(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [
            {"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": [1]},
            {"skill": "rigel.skill.test_writing", "payload": {}, "depends_on": [0]},
        ]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_defaults_missing_confidence_to_half(registry):
    payload = {"projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": []}]}]}
    assert _planner(registry, payload).plan(_goal()).plan_confidence == 0.5


def test_plan_handles_fenced_json(registry):
    payload_str = "```json\n" + json.dumps({
        "plan_confidence": 0.7,
        "projects": [{"title": "x", "description": "", "tasks": [
            {"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": []}]}],
    }) + "\n```"
    def fake_llm(messages, config, system_prompt=""):
        return payload_str, 0, 0
    planner = GoalPlanner(registry, llm=fake_llm, config_loader=lambda: object())
    assert planner.plan(_goal()).plan_confidence == 0.7
