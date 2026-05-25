from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import traceback
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from click.testing import CliRunner
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cli.run as cli_run
import services.andromeda_service as andromeda_service
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from agents.rigel.config import RigelConfig
from agents.vega.agent import VegaAgent
from agents.vega import pipeline as vega_pipeline
from core.contracts import FeedbackEvent, OutcomeType, RefineryFeedbackEvent, TaskContract
from core.llm.provider import ProviderConfig
from core.pulsar.registry import PulsarRegistry
from orion import OrionService
from orion.config import OrionConfig
from orion.core.candidate_store import CandidateStore
from orion.pipeline.heuristic_generation import (
    STREAM_DRIFT_ALERT,
    STREAM_FINE_TUNE_READY,
    STREAM_ROUTING_UPDATE,
)

DATASET_PATH = ROOT / "datasets" / "industry_scenarios.json"
REPORT_DIR = ROOT / "report"


@dataclass
class EvalCaseResult:
    suite: str
    status: str
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class EvalFailure(AssertionError):
    pass


class CapturingAether:
    def __init__(self) -> None:
        self.contracts: list[Any] = []
        self.events: list[tuple[str, dict]] = []
        self.closed = False

    def publish(self, contract) -> None:
        self.contracts.append(contract.model_copy(deep=True))

    def publish_event(self, stream: str, payload: dict) -> None:
        self.events.append((stream, payload))

    def close(self) -> None:
        self.closed = True


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def xadd(self, stream: str, fields: dict) -> str:
        self.messages.append((stream, dict(fields)))
        return f"{len(self.messages)}-0"

    async def aclose(self) -> None:
        return None


class DeterministicCorpus:
    def __init__(self, scenarios: list[dict[str, Any]]) -> None:
        self.scenarios = {scenario["id"]: scenario for scenario in scenarios}

    def vega_llm(self, messages: list[dict], config: ProviderConfig, system_prompt: str = ""):
        user = messages[-1]["content"]
        scenario = self._pick_vega_scenario(user)
        if "Requirements:" in user and "Test strategy:" not in user:
            payload = scenario["analysis_output"]
        elif "Test strategy:" in user:
            payload = scenario["test_design_output"]
        else:
            payload = scenario["bug_report_output"]
        return json.dumps(payload), 100, 80

    def rigel_llm(self, system: str, user: str) -> str:
        if "Rate whether this output fully satisfies the task" in user:
            return '{"score": 0.94, "gaps": []}'
        if "Write complete python code" in user and "idempotency" in user.lower():
            return (
                "def build_reservation_key(property_id, booking_id, attempt):\n"
                "    if not property_id or not booking_id:\n"
                "        raise ValueError('property_id and booking_id are required')\n"
                "    if attempt < 1:\n"
                "        raise ValueError('attempt must be >= 1')\n"
                "    return f\"{property_id}:{booking_id}:{attempt}\"\n"
            )
        if "Write pytest tests" in user:
            return (
                "def test_normalize_gtin_pads_to_fourteen_digits():\n"
                "    assert normalize_gtin('1234567890123') == '01234567890123'\n\n"
                "def test_normalize_gtin_rejects_non_numeric_values():\n"
                "    import pytest\n"
                "    with pytest.raises(ValueError):\n"
                "        normalize_gtin('abc')\n"
            )
        if "Review this pull request diff" in user:
            return (
                '{"findings": [{"severity": "high", "file": "services/patient_intake.py", '
                '"line": 18, "issue": "Sensitive patient data is logged directly", '
                '"suggestion": "Redact PHI before logging request payloads"}], '
                '"summary": "Logging introduces PHI exposure risk", "approved": false}'
            )
        if "Triage the following error" in user:
            return (
                '{"root_cause_hypothesis": "Observation validation accepts missing units for quantitative values", '
                '"confidence": 0.91, "suggested_fix_approach": "Require units whenever value is numeric", '
                '"next_step": "code_generation"}'
            )
        if "Refactor the following" in user:
            return (
                "def normalize_gtin(raw_gtin: str) -> str:\n"
                "    digits = ''.join(ch for ch in raw_gtin if ch.isdigit())\n"
                "    if len(digits) not in {8, 12, 13, 14}:\n"
                "        raise ValueError('invalid GTIN length')\n"
                "    return digits.zfill(14)\n"
            )
        if "Scaffold a service project using python" in user:
            return (
                '{"file_tree": {"app": {"__init__.py": "file", "main.py": "file"}, "tests": {"test_health.py": "file"}}, '
                '"files": [{"path": "app/main.py", "content": "def health():\\n    return {\\"status\\": \\"ok\\"}\\n"}, '
                '{"path": "tests/test_health.py", "content": "from app.main import health\\n\\ndef test_health():\\n    assert health()[\\"status\\"] == \\"ok\\"\\n"}], '
                '"instructions": "Install requirements and run pytest"}'
            )
        return (
            "def generated(value):\n"
            "    if value is None:\n"
            "        raise ValueError('value is required')\n"
            "    return {'value': value, 'status': 'ok'}\n"
        )

    def _pick_vega_scenario(self, text: str) -> dict[str, Any]:
        checks = [
            ("Finance ACH Payroll", "finance_ach_payroll"),
            ("Health FHIR Intake", "health_fhir_intake"),
            ("Hospitality Reservation Workflow", "hospitality_booking"),
            ("Retail GTIN Catalog Sync", "retail_gtin_catalog"),
            ("FIN-REQ-", "finance_ach_payroll"),
            ("HLTH-REQ-", "health_fhir_intake"),
            ("HOTEL-REQ-", "hospitality_booking"),
            ("RTL-REQ-", "retail_gtin_catalog"),
        ]
        for needle, scenario_id in checks:
            if needle in text:
                return self.scenarios[scenario_id]
        raise EvalFailure(f"Unable to resolve Vega scenario from prompt: {text[:120]}")


@contextmanager
def working_directory(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    corpus = DeterministicCorpus(dataset["scenarios"])

    results: list[EvalCaseResult] = []
    for suite_name, runner in [
        ("contracts_registry", lambda: run_contracts_registry_eval(dataset)),
        ("vega_pipeline", lambda: run_vega_eval(dataset, corpus)),
        ("rigel_skills", lambda: run_rigel_eval(corpus)),
        ("andromeda_routing", lambda: run_andromeda_eval(corpus)),
        ("cli_surface", lambda: run_cli_eval()),
        ("api_surface", lambda: run_api_eval()),
        ("orion_pipeline", lambda: run_orion_eval()),
        ("feedback_handshake", lambda: run_feedback_handshake_eval(dataset, corpus)),
    ]:
        try:
            results.append(runner())
        except Exception as exc:
            results.append(
                EvalCaseResult(
                    suite=suite_name,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    artifacts={"traceback": traceback.format_exc()},
                )
            )

    completed_at = datetime.now(timezone.utc)
    summary = build_summary(dataset, results, started_at, completed_at)
    write_reports(summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


def run_contracts_registry_eval(dataset: dict[str, Any]) -> EvalCaseResult:
    result = EvalCaseResult(suite="contracts_registry", status="passed")
    with TemporaryDirectory(prefix="galaxz-eval-contracts-") as temp_dir:
        registry = PulsarRegistry(db_path=str(Path(temp_dir) / "pulsar.db"))
        vega = VegaAgent(registry)
        rigel = RigelAgent(registry, rigel_config=RigelConfig(execution_calibration_enabled=False, _env_file=None))

        task = TaskContract(
            origin="evals",
            skill="requirements_to_test_cases",
            payload={"raw_requirements": dataset["scenarios"][0]["raw_requirements"]},
            confidence_threshold=0.65,
        )
        _expect(task.skill == "requirements_to_test_cases", "TaskContract preserves requested skill")
        _expect(registry.get_agent(vega.AGENT_ID) is not None, "Vega manifest registers in Pulsar")
        _expect(registry.get_agent(rigel.AGENT_ID) is not None, "Rigel manifest registers in Pulsar")
        _expect(
            len(registry.get_agents_for_skill("requirements_to_test_cases")) == 1,
            "Registry resolves Vega by QA skill",
        )
        _expect(
            len(registry.get_agents_for_skill("rigel.skill.code_generation")) == 1,
            "Registry resolves Rigel by engineering skill",
        )
        result.checks.extend([
            "TaskContract creation and validation",
            "Pulsar registration for Vega and Rigel",
            "Skill lookup for QA and engineering paths",
        ])
    return result


def run_vega_eval(dataset: dict[str, Any], corpus: DeterministicCorpus) -> EvalCaseResult:
    result = EvalCaseResult(suite="vega_pipeline", status="passed")
    artifacts: dict[str, Any] = {}
    for scenario in dataset["scenarios"]:
        aether = CapturingAether()
        with ExitStack() as stack:
            stack.enter_context(patch.object(vega_pipeline, "get_aether_client", lambda: aether))
            stack.enter_context(
                patch.object(
                    vega_pipeline,
                    "load_provider_config",
                    lambda _: ProviderConfig(provider="test", model="deterministic"),
                )
            )
            stack.enter_context(patch("agents.vega.stages.analyzer.call_llm", corpus.vega_llm))
            stack.enter_context(patch("agents.vega.stages.test_designer.call_llm", corpus.vega_llm))
            stack.enter_context(patch("agents.vega.stages.bug_reporter.call_llm", corpus.vega_llm))

            output = vega_pipeline.run_vega_pipeline(
                raw_requirements=scenario["raw_requirements"],
                test_results=scenario["test_results"],
                config_path="unused.yaml",
            )

        _expect(output["analyzer"]["total_count"] == scenario["analysis_output"]["total_count"], f"{scenario['id']} analyzer total_count matches")
        _expect(output["test_designer"]["total_count"] == scenario["test_design_output"]["total_count"], f"{scenario['id']} test designer total_count matches")
        _expect(output["bug_reporter"]["total_bugs"] == scenario["bug_report_output"]["total_bugs"], f"{scenario['id']} bug reporter total_bugs matches")
        _expect(aether.closed is True, f"{scenario['id']} closes Aether client")
        _expect(len(aether.contracts) == 9, f"{scenario['id']} publishes full Vega lifecycle")
        _expect(len(aether.events) == 1, f"{scenario['id']} emits refinery feedback")
        artifacts[scenario["id"]] = {
            "run_id": output["run_id"],
            "feedback_stream": aether.events[0][0],
            "bugs": output["bug_reporter"]["total_bugs"],
        }

    result.checks.extend([
        "Finance Vega flow",
        "Health Vega flow",
        "Hospitality Vega flow",
        "Retail Vega flow",
    ])
    result.artifacts = artifacts
    return result


def run_rigel_eval(corpus: DeterministicCorpus) -> EvalCaseResult:
    result = EvalCaseResult(suite="rigel_skills", status="passed")
    with TemporaryDirectory(prefix="galaxz-eval-rigel-") as temp_dir:
        registry = PulsarRegistry(db_path=str(Path(temp_dir) / "pulsar.db"))
        fake_aether = CapturingAether()
        with ExitStack() as stack:
            stack.enter_context(patch("agents.rigel.agent.get_aether_client", lambda: fake_aether))
            stack.enter_context(
                patch(
                    "agents.rigel.execution.subprocess.run",
                    lambda *args, **kwargs: subprocess.CompletedProcess(
                        args=args[0],
                        returncode=0,
                        stdout="PASS test_generated\n",
                        stderr="",
                    ),
                )
            )
            agent = RigelAgent(
                registry,
                rigel_config=RigelConfig(execution_calibration_enabled=True, execution_timeout_s=5, _env_file=None),
            )
            agent.llm = corpus.rigel_llm

            codegen = agent.run(
                "rigel.skill.code_generation",
                {
                    "spec": "Build a hospitality reservation idempotency helper.",
                    "language": "python",
                    "tests": (
                        "def test_build_reservation_key_includes_attempt():\n"
                        "    assert build_reservation_key('PROP1', 'BOOK1', 2) == 'PROP1:BOOK1:2'\n\n"
                        "def test_build_reservation_key_rejects_zero_attempt():\n"
                        "    import pytest\n"
                        "    with pytest.raises(ValueError):\n"
                        "        build_reservation_key('PROP1', 'BOOK1', 0)\n"
                    ),
                },
            )
            tests = agent.run(
                "rigel.skill.test_writing",
                {
                    "code": (
                        "def normalize_gtin(raw_gtin):\n"
                        "    digits = ''.join(ch for ch in raw_gtin if ch.isdigit())\n"
                        "    if len(digits) not in {8, 12, 13, 14}:\n"
                        "        raise ValueError('invalid GTIN length')\n"
                        "    return digits.zfill(14)\n"
                    ),
                    "test_framework": "pytest",
                },
            )
            review = agent.run(
                "rigel.skill.pr_review",
                {
                    "diff": "diff --git a/services/patient_intake.py b/services/patient_intake.py\n+logger.debug(payload)",
                },
            )
            triage = agent.run(
                "rigel.skill.debug_triage",
                {
                    "error_trace": "ValueError: quantitative observation missing units",
                    "language": "python",
                },
            )
            refactor = agent.run(
                "rigel.skill.refactor",
                {
                    "code": "def normalize_gtin(v): digits=''.join(c for c in v if c.isdigit()); return digits.zfill(14)",
                    "refactor_intent": "improve readability and validation",
                    "language": "python",
                },
            )
            scaffold = agent.run(
                "rigel.skill.scaffold",
                {
                    "project_type": "service",
                    "stack": "python",
                    "features": ["health endpoint", "pytest"],
                },
            )

        _expect(codegen["execution_result"]["outcome"] == "pass", "Rigel code generation is execution-calibrated")
        _expect(codegen["confidence"] >= 0.9, "Rigel code generation confidence is boosted by passing execution")
        _expect(tests["test_count"] >= 2, "Rigel test writing returns multiple tests")
        _expect(review["approved"] is False, "Rigel PR review blocks insecure diff")
        _expect(len(review["findings"]) == 1, "Rigel PR review returns structured findings")
        _expect(triage["next_step"] == "code_generation", "Rigel triage suggests follow-on code generation")
        _expect("normalize_gtin" in refactor["refactored_code"], "Rigel refactor returns code payload")
        _expect(len(scaffold["files"]) == 2, "Rigel scaffold returns file payloads")
        _expect(len(fake_aether.events) == 6, "Rigel emits feedback for each skill")
        result.checks.extend([
            "Code generation with execution calibration",
            "Test writing",
            "PR review",
            "Debug triage",
            "Refactor",
            "Scaffold",
        ])
        result.artifacts = {
            "feedback_events": len(fake_aether.events),
            "codegen_confidence": codegen["confidence"],
        }
    return result


def run_andromeda_eval(corpus: DeterministicCorpus) -> EvalCaseResult:
    result = EvalCaseResult(suite="andromeda_routing", status="passed")
    with TemporaryDirectory(prefix="galaxz-eval-router-") as temp_dir:
        registry = PulsarRegistry(db_path=str(Path(temp_dir) / "pulsar.db"))
        task_log = TaskLog(db_path=str(Path(temp_dir) / "tasks.db"))
        vega = VegaAgent(registry)
        fake_aether = CapturingAether()
        with ExitStack() as stack:
            stack.enter_context(patch("agents.rigel.agent.get_aether_client", lambda: fake_aether))
            rigel = RigelAgent(
                registry,
                rigel_config=RigelConfig(execution_calibration_enabled=False, _env_file=None),
            )
            rigel.llm = corpus.rigel_llm
            stack.enter_context(
                patch(
                    "agents.vega.agent.run_vega_pipeline",
                    lambda **kwargs: {
                        "run_id": "vega-eval-run",
                        "analyzer": {"total_count": 3},
                        "test_designer": {"total_count": 3, "test_cases": [{"tc_id": "FIN-TC-001"}]},
                        "bug_reporter": None,
                    },
                )
            )

            router = Andromeda(
                registry,
                task_log,
                agents={"vega": vega, "rigel": rigel},
            )
            vega_state = router.route(
                task_type="requirements_to_test_cases",
                required_skills=["requirements_to_test_cases"],
                payload={"raw_requirements": "Finance ACH Payroll"},
            )
            rigel_state = router.route(
                task_type="code_generation",
                required_skills=["rigel.skill.code_generation"],
                payload={"spec": "Build a hospitality reservation idempotency helper.", "language": "python"},
            )
            missing_state = router.route(
                task_type="missing",
                required_skills=["missing.skill"],
                payload={"task": "unroutable"},
            )

        _expect(vega_state["assigned_agent"] == "vega", "Andromeda routes QA work to Vega")
        _expect(rigel_state["assigned_agent"] == "rigel", "Andromeda routes engineering work to Rigel")
        _expect(missing_state["status"] == "no_agent_found", "Andromeda surfaces no-match routing cleanly")
        _expect(task_log.get(vega_state["task_id"]) is not None, "Andromeda persists Vega task state")
        _expect(task_log.get(rigel_state["task_id"]) is not None, "Andromeda persists Rigel task state")
        result.checks.extend([
            "Vega routing",
            "Rigel routing",
            "No-match routing",
            "Task log persistence",
        ])
        result.artifacts = {
            "vega_task_id": vega_state["task_id"],
            "rigel_task_id": rigel_state["task_id"],
        }
    return result


def run_cli_eval() -> EvalCaseResult:
    result = EvalCaseResult(suite="cli_surface", status="passed")
    runner = CliRunner()

    with runner.isolated_filesystem():
        requirements_path = Path("reqs.md")
        requirements_path.write_text("Finance ACH Payroll", encoding="utf-8")

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    cli_run,
                    "run_vega_pipeline",
                    lambda **kwargs: {
                        "run_id": "cli-vega-run",
                        "analyzer": {"total_count": 3},
                        "test_designer": {"total_count": 3},
                        "bug_reporter": {"total_bugs": 1},
                    },
                )
            )
            vega_cmd = runner.invoke(cli_run.galaxz, ["vega", "--input", str(requirements_path)])

            fake_router = SimpleNamespace(
                route=lambda **kwargs: {
                    "task_id": "cli-task-1",
                    "assigned_agent": "rigel",
                    "status": "complete",
                    "confidence": 0.91,
                }
            )
            stack.enter_context(patch("boot.boot", lambda: fake_router))
            route_cmd = runner.invoke(
                cli_run.galaxz,
                ["route", "--skill", "rigel.skill.code_generation", "--payload", '{"spec": "generate validator"}'],
            )

    _expect(vega_cmd.exit_code == 0, "CLI Vega command exits cleanly")
    _expect("Test cases generated: 3" in vega_cmd.output, "CLI Vega command prints summary")
    _expect(route_cmd.exit_code == 0, "CLI route command exits cleanly")
    _expect("assigned_agent: rigel" in route_cmd.output, "CLI route command prints routed agent")
    result.checks.extend([
        "CLI Vega command",
        "CLI route command",
    ])
    return result


def run_api_eval() -> EvalCaseResult:
    result = EvalCaseResult(suite="api_surface", status="passed")
    auth_headers = {"Authorization": "Bearer eval-key"}

    class FakeRegistry:
        def health_check(self) -> dict:
            return {"status": "ok", "skill_count": 2, "agents": ["rigel", "vega"]}

        def get_all_skills(self) -> list:
            return [object(), object()]

        def get_agents_for_skill(self, skill_id: str) -> list:
            return ["rigel"] if skill_id == "rigel.skill.code_generation" else []

    class FakeAndromeda:
        def __init__(self, db_path: Path, dataset_path: Path) -> None:
            self.registry = FakeRegistry()
            self.review_queue = FakeReviewQueue()
            self.task_log = FakeTaskLog()
            self.orion = SimpleNamespace(
                _cfg=SimpleNamespace(db_path=str(db_path), dataset_path=str(dataset_path)),
            )

        def route(self, **kwargs) -> dict:
            task = kwargs["task"]
            return {
                "task_id": "api-task-1",
                "task_type": task.skill.split(".")[-1],
                "required_skills": [task.skill],
                "assigned_agent": "rigel",
                "status": "complete",
                "confidence": 0.88,
                "payload": task.payload,
            }

    class FakeReviewQueue:
        def __init__(self) -> None:
            self._items = {
                "11111111-1111-4111-8111-111111111111": {
                    "task_id": "11111111-1111-4111-8111-111111111111",
                    "task_type": "code_generation",
                    "confidence": 0.38,
                    "payload": {"spec": "repair validator"},
                    "status": "pending",
                },
                "22222222-2222-4222-8222-222222222222": {
                    "task_id": "22222222-2222-4222-8222-222222222222",
                    "task_type": "requirements_to_test_cases",
                    "confidence": 0.41,
                    "payload": {"raw_requirements": "Finance ACH Payroll"},
                    "status": "pending",
                },
            }

        def get_pending(self) -> list[dict]:
            return [item for item in self._items.values() if item["status"] == "pending"]

        def get_by_task_id(self, task_id: str) -> dict | None:
            return self._items.get(task_id)

        def resolve(self, task_id: str, new_status: str, reviewer_notes: str | None = None) -> bool:
            item = self._items.get(task_id)
            if item is None or item["status"] != "pending":
                return False
            item["status"] = new_status
            item["reviewer_notes"] = reviewer_notes
            return True

    class FakeTaskLog:
        def __init__(self) -> None:
            self.status_updates: list[tuple[str, str, str]] = []

        def recent(self, limit: int) -> list[dict]:
            return [{"task_id": "recent-task", "status": "complete"}][:limit]

        def stats(self) -> dict:
            return {"total": 2, "complete": 1, "failed": 0, "escalated": 1}

        def update_status(self, task_id: str, task_type: str, new_status: str) -> None:
            self.status_updates.append((task_id, task_type, new_status))

    with TemporaryDirectory(prefix="galaxz-eval-api-") as temp_dir:
        temp_root = Path(temp_dir)
        db_path = temp_root / "events.db"
        dataset_path = temp_root / "datasets"
        dataset_path.mkdir()
        (dataset_path / "code_generation.jsonl").write_text('{"prompt": "p", "completion": "c"}\n', encoding="utf-8")
        candidate_approve, candidate_reject = _seed_finetune_candidates(
            db_path.parent / "candidates.db"
        )
        fake_aether = CapturingAether()
        fake = FakeAndromeda(db_path, dataset_path)

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"GALAXZ_API_KEY": "eval-key"}))
            stack.enter_context(patch.object(andromeda_service, "boot", lambda: fake))
            stack.enter_context(patch.object(andromeda_service, "get_aether_client", lambda: fake_aether))
            with TestClient(andromeda_service.app) as client:
                health = client.get("/health")
                unauthorized = client.post(
                    "/task",
                    json={"task": "Generate validator", "skill_id": "code_generation"},
                )
                task = client.post(
                    "/task",
                    json={"task": "Generate validator", "skill_id": "code_generation"},
                    headers=auth_headers,
                )
                status = client.get("/status")
                review_queue = client.get("/review/queue")
                review_approved = client.post(
                    "/review/queue/11111111-1111-4111-8111-111111111111/approve",
                    json={"reviewer_notes": "acceptable"},
                    headers=auth_headers,
                )
                review_rejected = client.post(
                    "/review/queue/22222222-2222-4222-8222-222222222222/reject",
                    json={"reviewer_notes": "needs correction"},
                    headers=auth_headers,
                )
                finetune_candidates = client.get("/finetune/candidates", headers=auth_headers)
                finetune_approved = client.post(
                    f"/finetune/candidates/{candidate_approve}/approve",
                    json={"reviewed_by": "eval", "reviewer_note": "ship it"},
                    headers=auth_headers,
                )
                finetune_rejected = client.post(
                    f"/finetune/candidates/{candidate_reject}/reject",
                    json={"reviewed_by": "eval", "reviewer_note": "bad sample"},
                    headers=auth_headers,
                )

    _expect(health.status_code == 200, "API health endpoint is healthy")
    _expect(unauthorized.status_code == 401, "API write endpoints require bearer auth when configured")
    _expect(task.status_code == 200, "API task endpoint returns success")
    _expect(task.json()["required_skills"] == ["rigel.skill.code_generation"], "API normalizes short Rigel skill ids")
    _expect(status.status_code == 200, "API status endpoint returns service rollup")
    _expect(status.json()["orion"]["training_examples"] == 1, "API status includes Orion dataset counts")
    _expect(review_queue.status_code == 200, "API review queue endpoint returns pending tasks")
    _expect(len(review_queue.json()) == 2, "API review queue exposes pending escalations")
    _expect(review_approved.status_code == 200, "API review approve endpoint resolves a task")
    _expect(review_rejected.status_code == 200, "API review reject endpoint resolves a task")
    _expect(finetune_candidates.status_code == 200, "API fine-tune candidates endpoint returns pending candidates")
    _expect(len(finetune_candidates.json()["candidates"]) == 2, "API fine-tune candidates exposes pending candidates")
    _expect(finetune_approved.status_code == 200, "API fine-tune candidate approve endpoint resolves a candidate")
    _expect(finetune_approved.json()["status"] == "approved", "API fine-tune approve marks candidate approved")
    _expect(finetune_rejected.status_code == 200, "API fine-tune candidate reject endpoint resolves a candidate")
    _expect(finetune_rejected.json()["status"] == "rejected", "API fine-tune reject marks candidate rejected")
    result.checks.extend([
        "FastAPI health endpoint",
        "FastAPI bearer auth for write endpoints",
        "FastAPI task routing endpoint",
        "FastAPI status endpoint",
        "FastAPI review queue approve/reject endpoints",
        "FastAPI fine-tune candidate approve/reject endpoints",
    ])
    return result


def _seed_finetune_candidates(db_path: Path) -> tuple[str, str]:
    store = CandidateStore(str(db_path))
    approve = store.add("vega", 120, 0.91)
    reject = store.add("rigel", 140, 0.89)
    return approve.candidate_id, reject.candidate_id


def run_orion_eval() -> EvalCaseResult:
    result = EvalCaseResult(suite="orion_pipeline", status="passed")
    return asyncio.run(_run_orion_eval_async(result))


async def _run_orion_eval_async(result: EvalCaseResult) -> EvalCaseResult:
    with TemporaryDirectory(prefix="galaxz-eval-orion-") as temp_dir:
        temp_root = Path(temp_dir)
        registry = PulsarRegistry(db_path=str(temp_root / "pulsar.db"))
        VegaAgent(registry)
        RigelAgent(registry, rigel_config=RigelConfig(execution_calibration_enabled=False, _env_file=None))

        config = OrionConfig(
            redis_url="redis://unused",
            db_path=str(temp_root / "events.db"),
            dataset_path=str(temp_root / "datasets"),
            extraction_interval_hours=999,
            heuristic_cycle_interval_hours=999,
            routing_min_sample_size=2,
            routing_confidence_delta=0.1,
            drift_confidence_drop=0.1,
            fine_tune_correction_count=1,
            fine_tune_correction_rate=0.2,
        )
        service = OrionService(config, registry=registry)
        await service._event_log.init_db(config.db_path)

        with working_directory(temp_root):
            accepted = await service.ingest(
                RefineryFeedbackEvent(
                    task_id=uuid4(),
                    agent_id="vega",
                    skill="requirements_to_test_cases",
                    outcome="success",
                    confidence_score=0.91,
                    latency_ms=120,
                )
            )
            rejected = await service.ingest(
                RefineryFeedbackEvent(
                    task_id=uuid4(),
                    agent_id="vega",
                    skill="requirements_to_test_cases",
                    outcome="fail",
                    confidence_score=0.10,
                    latency_ms=120,
                )
            )

        now = datetime.now(timezone.utc)
        rows = [
            FeedbackEvent(
                task_id=uuid4(),
                task_category="qa.finance",
                agent_id="rigel",
                outcome=OutcomeType.completed,
                confidence_score=0.98,
                input_hash="finance-high",
                agent_output={"input": "finance prompt", "output": "good"},
                latency_ms=50,
                timestamp=now,
            ),
            FeedbackEvent(
                task_id=uuid4(),
                task_category="qa.finance",
                agent_id="vega",
                outcome=OutcomeType.corrected,
                confidence_score=0.70,
                input_hash="finance-corrected",
                agent_output={"input": "finance bad", "output": "wrong"},
                human_correction={"output": "fixed"},
                latency_ms=60,
                timestamp=now,
            ),
            FeedbackEvent(
                task_id=uuid4(),
                task_category="qa.finance",
                agent_id="rigel",
                outcome=OutcomeType.failed,
                confidence_score=0.20,
                input_hash="finance-low-1",
                agent_output={"input": "finance low", "output": "bad"},
                latency_ms=70,
                timestamp=now - timedelta(days=1),
            ),
            FeedbackEvent(
                task_id=uuid4(),
                task_category="qa.finance",
                agent_id="rigel",
                outcome=OutcomeType.completed,
                confidence_score=0.95,
                input_hash="finance-old-1",
                agent_output={"input": "finance old", "output": "good"},
                latency_ms=70,
                timestamp=now - timedelta(days=20),
            ),
            FeedbackEvent(
                task_id=uuid4(),
                task_category="qa.finance",
                agent_id="rigel",
                outcome=OutcomeType.completed,
                confidence_score=0.96,
                input_hash="finance-old-2",
                agent_output={"input": "finance old 2", "output": "good"},
                latency_ms=70,
                timestamp=now - timedelta(days=25),
            ),
        ]
        for row in rows:
            await service._event_log.append(row)

        await service.run_extraction_cycle()

        fake_redis = FakeAsyncRedis()
        with patch("orion.pipeline.heuristic_generation.aioredis.from_url", lambda *args, **kwargs: fake_redis):
            await service.run_heuristic_cycle()

        _expect(accepted["eligible"] is True, "Orion ingest accepts high-confidence refinery feedback")
        _expect(rejected["eligible"] is False, "Orion ingest quarantines weak refinery feedback")
        with sqlite3.connect(config.db_path) as _db:
            _accepted_count = _db.execute(
                "SELECT COUNT(*) FROM events WHERE quarantined=0"
            ).fetchone()[0]
            _rejected_count = _db.execute(
                "SELECT COUNT(*) FROM events WHERE quarantined=1"
            ).fetchone()[0]
            _curated_count = _db.execute(
                "SELECT COUNT(*) FROM curated_events"
            ).fetchone()[0]
        _expect(_accepted_count > 0, "Orion ingest stores accepted examples in events.db")
        _expect(_rejected_count > 0, "Orion ingest stores rejected examples as quarantined in events.db")
        _expect(_curated_count > 0, "Orion extraction cycle curates events into dataset")
        emitted_streams = {stream for stream, _ in fake_redis.messages}
        _expect(STREAM_ROUTING_UPDATE in emitted_streams, "Orion heuristics emit routing update")
        _expect(STREAM_DRIFT_ALERT in emitted_streams, "Orion heuristics emit drift alert")
        _expect(STREAM_FINE_TUNE_READY in emitted_streams, "Orion heuristics emit fine-tune trigger")
        _expect(
            not (temp_root / "orion_datasets").exists(),
            "Orion no longer writes to legacy hard-coded dataset directory",
        )

        result.checks.extend([
            "Direct Orion ingest for accepted and rejected feedback",
            "Dataset curation cycle",
            "Heuristic cycle with routing, drift, and fine-tune signals",
        ])
        result.artifacts = {
            "heuristic_streams": sorted(emitted_streams),
            "ingest_dataset_root": str(temp_root / "datasets"),
        }
        return result


def run_feedback_handshake_eval(dataset: dict[str, Any], corpus: DeterministicCorpus) -> EvalCaseResult:
    result = EvalCaseResult(suite="feedback_handshake", status="passed")
    return asyncio.run(_run_feedback_handshake_async(dataset, corpus, result))


async def _run_feedback_handshake_async(dataset: dict[str, Any], corpus: DeterministicCorpus, result: EvalCaseResult) -> EvalCaseResult:
    scenario = next(item for item in dataset["scenarios"] if item["id"] == "finance_ach_payroll")
    with TemporaryDirectory(prefix="galaxz-eval-feedback-") as temp_dir:
        temp_root = Path(temp_dir)
        registry = PulsarRegistry(db_path=str(temp_root / "pulsar.db"))
        task_log = TaskLog(db_path=str(temp_root / "tasks.db"))
        config = OrionConfig(
            redis_url="redis://unused",
            db_path=str(temp_root / "events.db"),
            dataset_path=str(temp_root / "datasets"),
        )
        orion = OrionService(config, registry=registry)
        await orion._event_log.init_db(config.db_path)

        shared_aether = CapturingAether()
        with ExitStack() as stack:
            stack.enter_context(patch.object(vega_pipeline, "get_aether_client", lambda: shared_aether))
            stack.enter_context(
                patch.object(
                    vega_pipeline,
                    "load_provider_config",
                    lambda _: ProviderConfig(provider="test", model="deterministic"),
                )
            )
            stack.enter_context(patch("agents.vega.stages.analyzer.call_llm", corpus.vega_llm))
            stack.enter_context(patch("agents.vega.stages.test_designer.call_llm", corpus.vega_llm))
            stack.enter_context(patch("agents.vega.stages.bug_reporter.call_llm", corpus.vega_llm))
            stack.enter_context(patch("agents.rigel.agent.get_aether_client", lambda: shared_aether))

            vega = VegaAgent(registry)
            rigel = RigelAgent(
                registry,
                rigel_config=RigelConfig(execution_calibration_enabled=False, _env_file=None),
            )
            rigel.llm = corpus.rigel_llm
            router = Andromeda(registry, task_log, agents={"vega": vega, "rigel": rigel})

            vega_state = router.route(
                task_type="defect_reporting",
                required_skills=["defect_reporting"],
                payload={
                    "raw_requirements": scenario["raw_requirements"],
                    "test_results": scenario["test_results"],
                },
            )
            rigel_state = router.route(
                task_type="code_generation",
                required_skills=["rigel.skill.code_generation"],
                payload={"spec": "Build a hospitality reservation idempotency helper.", "language": "python"},
            )

        ingested = []
        with working_directory(temp_root):
            for _, payload in shared_aether.events:
                event = RefineryFeedbackEvent(**payload)
                ingested.append(await orion.ingest(event))

        _expect(vega_state["status"] == "complete", "Vega route completes during feedback handshake")
        _expect(rigel_state["status"] == "complete", "Rigel route completes during feedback handshake")
        _expect(len(shared_aether.events) >= 2, "Agents emit refinery feedback events")
        _expect(any(item["eligible"] for item in ingested), "Orion accepts at least one agent feedback event")
        result.checks.extend([
            "Andromeda to Vega execution",
            "Andromeda to Rigel execution",
            "Agent feedback payload compatibility with Orion ingest",
        ])
        result.artifacts = {
            "feedback_events": len(shared_aether.events),
            "eligible_ingests": sum(1 for item in ingested if item["eligible"]),
        }
        return result


def build_summary(
    dataset: dict[str, Any],
    results: list[EvalCaseResult],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    passed = sum(1 for item in results if item.status == "passed")
    failed = len(results) - passed
    return {
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "dataset_sources": dataset["sources"],
        "scenario_count": len(dataset["scenarios"]),
        "passed": passed,
        "failed": failed,
        "results": [asdict(item) for item in results],
    }


def write_reports(summary: dict[str, Any]) -> None:
    json_path = REPORT_DIR / "latest_results.json"
    md_path = REPORT_DIR / "latest_results.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Eval Execution Report",
        "",
        f"- Started: `{summary['started_at']}`",
        f"- Completed: `{summary['completed_at']}`",
        f"- Duration: `{summary['duration_seconds']}s`",
        f"- Scenarios: `{summary['scenario_count']}`",
        f"- Passed suites: `{summary['passed']}`",
        f"- Failed suites: `{summary['failed']}`",
        "",
        "## Suites",
        "",
    ]
    for item in summary["results"]:
        lines.append(f"### {item['suite']}")
        lines.append(f"- Status: `{item['status']}`")
        for check in item["checks"]:
            lines.append(f"- Check: {check}")
        for warning in item["warnings"]:
            lines.append(f"- Warning: {warning}")
        if item["error"]:
            lines.append(f"- Error: `{item['error']}`")
        if item["artifacts"]:
            lines.append(f"- Artifacts: `{json.dumps(item['artifacts'], sort_keys=True)}`")
        lines.append("")

    lines.extend([
        "## Dataset Sources",
        "",
    ])
    for source in summary["dataset_sources"]:
        lines.append(f"- {source['domain']}: {source['standard']} ({source['url']})")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise EvalFailure(message)


if __name__ == "__main__":
    raise SystemExit(main())
