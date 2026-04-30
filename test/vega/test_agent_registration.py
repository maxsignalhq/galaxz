from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.vega.agent import VegaAgent
from core.pulsar.registry import PulsarRegistry


def test_vega_boot_registers_manifest_in_pulsar(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    manifest = registry.get_agent("vega")
    assert manifest is not None
    assert manifest.agent_id == "vega"
    assert manifest.agent_name == "Vega QA Agent"
    assert {skill.skill_id for skill in manifest.skills} >= {
        "requirements_to_test_cases",
        "test_case_execution",
        "defect_reporting",
    }
    assert "vega" in {agent.agent_id for agent in registry.list_agents()}


def test_pulsar_discovers_vega_for_requirements_to_test_cases(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    matches = registry.get_agents_for_skill("requirements_to_test_cases")
    assert [agent.agent_id for agent in matches] == ["vega"]


def test_andromeda_routes_requirements_to_test_cases_via_registry(monkeypatch, tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    vega = VegaAgent(registry)

    monkeypatch.setattr(
        "agents.vega.agent.run_vega_pipeline",
        lambda **kwargs: {
            "run_id": "vega-run-123",
            "analyzer": {"total_count": 1},
            "test_designer": {
                "test_cases": [{"tc_id": "TC-001", "title": "Login success"}],
                "total_count": 1,
            },
            "bug_reporter": None,
        },
    )

    andromeda = Andromeda(
        registry,
        task_log,
        agents={"vega": vega},
    )

    state = andromeda.route(
        task_type="requirements_to_test_cases",
        required_skills=["requirements_to_test_cases"],
        payload={"raw_requirements": "Users can log in."},
    )

    assert state["status"] == "complete"
    assert state["assigned_agent"] == "vega"
    assert state["result"]["total_count"] == 1
    assert "selected vega" in state["assignment_reason"]

    persisted = task_log.get(state["task_id"])
    assert persisted is not None
    assert persisted["assigned_agent"] == "vega"
