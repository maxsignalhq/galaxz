from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.vega.agent import VegaAgent
from core.contracts import RefineryFeedbackEvent, validate_feedback_event
from core.pulsar.registry import PulsarRegistry


def test_vega_boot_registers_manifest_in_pulsar(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    manifest = registry.get_agent("vega")
    assert manifest is not None
    assert manifest.agent_id == "vega"
    assert manifest.agent_name == "Vega QA Agent"
    assert {skill.skill_id for skill in manifest.skills} >= {
        "vega.skill.requirements_to_test_cases",
        "vega.skill.test_case_execution",
        "vega.skill.defect_reporting",
    }
    assert "vega" in {agent.agent_id for agent in registry.list_agents()}


def test_pulsar_discovers_vega_for_requirements_to_test_cases(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    matches = registry.get_agents_for_skill("vega.skill.requirements_to_test_cases")
    assert [agent.agent_id for agent in matches] == ["vega"]


def test_pulsar_discovers_vega_for_legacy_qa_skill_ids(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    assert [agent.agent_id for agent in registry.get_agents_for_skill("requirements_to_test_cases")] == ["vega"]
    assert [agent.agent_id for agent in registry.get_agents_for_skill("defect_reporting")] == ["vega"]


def test_vega_feedback_accepts_emitted_legacy_skill_ids(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))

    VegaAgent(registry)

    manifest = registry.get_agent("vega")
    event = RefineryFeedbackEvent(
        task_id="00000000-0000-0000-0000-000000000001",
        agent_id="vega",
        skill="requirements_to_test_cases",
        outcome="success",
        confidence_score=0.88,
        latency_ms=10,
    )

    assert manifest is not None
    assert validate_feedback_event(event, manifest) == event


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
        required_skills=["vega.skill.requirements_to_test_cases"],
        payload={"raw_requirements": "Users can log in."},
    )

    assert state["status"] == "complete"
    assert state["assigned_agent"] == "vega"
    assert state["result"]["total_count"] == 1
    assert "selected vega" in state["assignment_reason"]

    persisted = task_log.get(state["task_id"])
    assert persisted is not None
    assert persisted["assigned_agent"] == "vega"


def test_vega_requirements_to_test_cases_falls_back_when_pipeline_fails(monkeypatch, tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    vega = VegaAgent(registry)

    def fail_pipeline(**kwargs):
        raise ValueError("malformed model JSON")

    monkeypatch.setattr("agents.vega.agent.run_vega_pipeline", fail_pipeline)

    result = vega.run(
        "requirements_to_test_cases",
        {
            "raw_requirements": (
                "Write a Python script that converts measurements like Celsius to Fahrenheit "
                "or pounds to kilograms."
            )
        },
    )

    assert result["confidence"] >= 0.65
    assert result["result"]["total_count"] >= 3
    assert any(case["title"] == "Convert Celsius to Fahrenheit" for case in result["result"]["test_cases"])
    assert result["artifacts"]["fallback_reason"] == "malformed model JSON"


def test_vega_fallback_uses_current_word_frequency_requirements(monkeypatch, tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    vega = VegaAgent(registry)

    def fail_pipeline(**kwargs):
        raise ValueError("malformed model JSON")

    monkeypatch.setattr("agents.vega.agent.run_vega_pipeline", fail_pipeline)

    result = vega.run(
        "requirements_to_test_cases",
        {
            "raw_requirements": (
                "Write a Python script that has Word Frequency Counter. "
                "Generated implementation from Rigel:\n"
                "def word_frequency(text): return {}"
            )
        },
    )

    titles = [case["title"] for case in result["result"]["test_cases"]]
    assert "Count repeated words in plain text" in titles
    assert "Convert Celsius to Fahrenheit" not in titles
    assert all("Measurement converter" not in " ".join(case["preconditions"]) for case in result["result"]["test_cases"])
