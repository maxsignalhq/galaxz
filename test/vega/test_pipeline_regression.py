import json

import pytest

from agents.vega import pipeline
from agents.vega.lifecycle import TaskStatus, VegaStage
from core.llm.provider import ProviderConfig


class CapturingAether:
    def __init__(self) -> None:
        self.contracts = []
        self.closed = False

    def publish(self, contract) -> None:
        self.contracts.append(contract.model_copy(deep=True))

    def close(self) -> None:
        self.closed = True


def fake_vega_llm(messages, config, system_prompt=""):
    user = messages[-1]["content"]
    if "Requirements:" in user and "Test strategy:" not in user:
        return json.dumps(
            {
                "requirements": [
                    {
                        "req_id": "REQ-001",
                        "title": "Login",
                        "description": "Verified users can log in",
                        "category": "functional",
                        "priority": "high",
                        "testable": True,
                        "ambiguity_flag": False,
                        "ambiguity_note": None,
                    },
                    {
                        "req_id": "REQ-002",
                        "title": "Lockout",
                        "description": "Accounts lock after repeated failures",
                        "category": "functional",
                        "priority": "high",
                        "testable": True,
                        "ambiguity_flag": False,
                        "ambiguity_note": None,
                    },
                ],
                "total_count": 2,
                "ambiguous_count": 0,
                "untestable_count": 0,
                "summary": "Login and lockout requirements",
            }
        ), 100, 80

    if "Test strategy:" in user:
        return json.dumps(
            {
                "test_cases": [
                    {
                        "tc_id": "TC-001",
                        "req_id": "REQ-001",
                        "title": "Login success",
                        "preconditions": ["Verified user exists"],
                        "steps": ["Submit valid credentials"],
                        "expected_result": "JWT returned",
                        "test_type": "positive",
                        "priority": "high",
                        "automated": True,
                    },
                    {
                        "tc_id": "TC-002",
                        "req_id": "REQ-002",
                        "title": "Lockout after failures",
                        "preconditions": ["Verified user exists"],
                        "steps": ["Submit invalid password five times"],
                        "expected_result": "Account locked",
                        "test_type": "negative",
                        "priority": "high",
                        "automated": True,
                    },
                ],
                "total_count": 2,
                "coverage_summary": {"REQ-001": 1, "REQ-002": 1},
                "uncovered_reqs": [],
            }
        ), 100, 80

    return json.dumps(
        {
            "bug_reports": [
                {
                    "bug_id": "BUG-001",
                    "tc_id": "TC-002",
                    "req_id": "REQ-002",
                    "title": "Account does not lock",
                    "severity": "critical",
                    "description": "Lockout policy was not enforced",
                    "steps_to_reproduce": ["Submit invalid password five times"],
                    "expected": "Account locked",
                    "actual": "Login attempts continue",
                    "suggested_fix": "Enforce lockout counter",
                    "rigel_handoff": True,
                }
            ],
            "total_bugs": 1,
            "critical_count": 1,
            "rigel_handoffs": ["BUG-001"],
            "pass_rate": 0.5,
        }
    ), 100, 80


def test_vega_pipeline_publishes_stage_lifecycle_without_live_llm(monkeypatch):
    aether = CapturingAether()
    monkeypatch.setattr(pipeline, "get_aether_client", lambda: aether)
    monkeypatch.setattr(
        pipeline,
        "load_provider_config",
        lambda _: ProviderConfig(provider="test", model="deterministic"),
    )

    import agents.vega.stages.analyzer as analyzer
    import agents.vega.stages.bug_reporter as bug_reporter
    import agents.vega.stages.test_designer as test_designer

    monkeypatch.setattr(analyzer, "call_llm", fake_vega_llm)
    monkeypatch.setattr(test_designer, "call_llm", fake_vega_llm)
    monkeypatch.setattr(bug_reporter, "call_llm", fake_vega_llm)

    result = pipeline.run_vega_pipeline(
        raw_requirements="Users can log in. Accounts lock after repeated failures.",
        test_results=[
            {"tc_id": "TC-001", "status": "pass"},
            {"tc_id": "TC-002", "status": "fail", "actual_result": "Login attempts continue"},
        ],
        config_path="unused.yaml",
    )

    assert result["analyzer"]["total_count"] == 2
    assert result["test_designer"]["total_count"] == 2
    assert result["bug_reporter"]["total_bugs"] == 1
    assert aether.closed is True

    lifecycle = [(contract.stage, contract.status) for contract in aether.contracts]
    assert lifecycle == [
        (VegaStage.analyzer, TaskStatus.pending),
        (VegaStage.analyzer, TaskStatus.running),
        (VegaStage.analyzer, TaskStatus.complete),
        (VegaStage.test_designer, TaskStatus.pending),
        (VegaStage.test_designer, TaskStatus.running),
        (VegaStage.test_designer, TaskStatus.complete),
        (VegaStage.bug_reporter, TaskStatus.pending),
        (VegaStage.bug_reporter, TaskStatus.running),
        (VegaStage.bug_reporter, TaskStatus.complete),
    ]
    assert {contract.run_id for contract in aether.contracts} == {result["run_id"]}


def test_vega_pipeline_publishes_failed_stage_contract(monkeypatch):
    aether = CapturingAether()
    monkeypatch.setattr(pipeline, "get_aether_client", lambda: aether)
    monkeypatch.setattr(
        pipeline,
        "load_provider_config",
        lambda _: ProviderConfig(provider="test", model="deterministic"),
    )

    def fail_analyzer(*args, **kwargs):
        raise RuntimeError("analyzer unavailable")

    monkeypatch.setattr(pipeline, "run_analyzer", fail_analyzer)

    with pytest.raises(RuntimeError, match="analyzer unavailable"):
        pipeline.run_vega_pipeline(raw_requirements="REQ-001: Login")

    assert [(c.stage, c.status) for c in aether.contracts] == [
        (VegaStage.analyzer, TaskStatus.pending),
        (VegaStage.analyzer, TaskStatus.running),
        (VegaStage.analyzer, TaskStatus.failed),
    ]
    assert aether.contracts[-1].error == "analyzer unavailable"
    assert aether.closed is True
