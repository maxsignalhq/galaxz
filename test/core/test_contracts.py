from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.contracts import (
    RefineryFeedbackEvent,
    SkillDefinition,
    SkillManifest,
    TaskContract,
    validate_feedback_event,
)


def test_task_contract_rejects_missing_skill_and_negative_confidence_threshold():
    with pytest.raises(ValidationError) as excinfo:
        TaskContract(
            origin="test",
            payload={"x": 1},
            confidence_threshold=-0.1,
        )

    message = str(excinfo.value)
    assert "skill" in message
    assert "confidence_threshold" in message


@pytest.mark.parametrize(
    "model",
    [
        TaskContract(
            task_id=uuid4(),
            origin="api",
            skill="requirements_to_test_cases",
            payload={"raw_requirements": "Users can log in."},
            confidence_threshold=0.7,
            deadline_ms=5000,
        ),
        SkillManifest(
            agent_id="vega",
            agent_name="Vega QA Agent",
            version="0.1.0",
            health_endpoint="http://vega:8080/health",
            skills=[
                SkillDefinition(
                    skill_id="requirements_to_test_cases",
                    description="Generate test cases from requirements.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            ],
        ),
        RefineryFeedbackEvent(
            task_id=uuid4(),
            agent_id="vega",
            skill="requirements_to_test_cases",
            outcome="success",
            confidence_score=0.9,
            execution_outcome="pass",
            latency_ms=120,
        ),
    ],
)
def test_contract_round_trip_json(model):
    encoded = model.model_dump_json()
    decoded = type(model).model_validate_json(encoded)
    assert decoded == model


def test_validate_feedback_event_rejects_skill_manifest_mismatch():
    manifest = SkillManifest(
        agent_id="vega",
        agent_name="Vega QA Agent",
        version="0.1.0",
        health_endpoint="http://vega:8080/health",
        skills=[
            SkillDefinition(
                skill_id="requirements_to_test_cases",
                description="Generate test cases from requirements.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        ],
    )
    event = RefineryFeedbackEvent(
        task_id=uuid4(),
        agent_id="vega",
        skill="defect_reporting",
        outcome="fail",
        confidence_score=0.2,
        latency_ms=80,
    )

    with pytest.raises(ValueError, match="not registered"):
        validate_feedback_event(event, manifest)


def test_task_contract_workspace_root_defaults_to_none():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
    )
    assert task.workspace_root is None


def test_task_contract_workspace_root_round_trips():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
        workspace_root="/Users/dev/my-project",
    )
    restored = TaskContract.model_validate_json(task.model_dump_json())
    assert restored.workspace_root == "/Users/dev/my-project"


def test_task_contract_output_path_defaults_to_none():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
    )
    assert task.output_path is None


def test_task_contract_output_path_round_trips():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
        output_path="src/weather.py",
    )
    restored = TaskContract.model_validate_json(task.model_dump_json())
    assert restored.output_path == "src/weather.py"
