import time
from uuid import uuid4

from agents.vega.lifecycle import TaskStatus, VegaStage, VegaStageRecord, transition_status
from agents.vega.stages.analyzer import AnalyzerInput, AnalyzerOutput, run_analyzer
from agents.vega.stages.bug_reporter import (
    BugReporterInput,
    BugReporterOutput,
    TestResult,
    run_bug_reporter,
)
from agents.vega.stages.test_designer import (
    TestDesignerInput,
    TestDesignerOutput,
    run_test_designer,
)
from core.aether.client import get_aether_client
from core.contracts import RefineryFeedbackEvent
from core.llm.provider import load_provider_config

FEEDBACK_STREAM = "galaxz.feedback.vega"


def _normalize_test_results(raw: list[dict] | dict) -> list[dict]:
    if isinstance(raw, dict):
        items = raw.get("results")
        if not isinstance(items, list):
            raise ValueError("test_results dict must contain a list under 'results'")
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("test_results must be a list or a dict with a 'results' list")

    normalized: list[dict] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        status_raw = str(item.get("status", "")).strip().lower()
        status = {
            "pass": "pass",
            "passed": "pass",
            "ok": "pass",
            "success": "pass",
            "fail": "fail",
            "failed": "fail",
            "error": "fail",
            "blocked": "blocked",
            "skip": "skipped",
            "skipped": "skipped",
        }.get(status_raw, "fail")
        normalized.append({
            "tc_id": item.get("tc_id") or item.get("test_id") or item.get("id") or f"TC-{idx + 1:03d}",
            "status": status,
            "actual_result": item.get("actual_result") or item.get("actual"),
            "error_log": item.get("error_log") or item.get("error"),
        })
    return normalized


def run_vega_pipeline(
    raw_requirements: str,
    test_results: list[dict] | dict | None = None,
    config_path: str = "config/providers.yaml",
    source_type: str = "plain",
) -> dict:
    config = load_provider_config(config_path)
    aether = get_aether_client()
    run_id = str(uuid4())
    start_ms = time.monotonic()
    outcome = "fail"

    analyzer_output: AnalyzerOutput
    test_designer_output: TestDesignerOutput
    bug_reporter_output: BugReporterOutput | None = None

    try:
        # Stage 1: Analyzer
        print(f"[vega] stage=analyzer run_id={run_id} starting")
        analyzer_input = AnalyzerInput(raw_requirements=raw_requirements, source_type=source_type)
        contract = VegaStageRecord(
            run_id=run_id,
            stage=VegaStage.analyzer,
            status=TaskStatus.pending,
            provider=config.provider,
            model=config.model,
            input=analyzer_input.model_dump(),
        )
        aether.publish(contract)
        contract = transition_status(contract, TaskStatus.running)
        aether.publish(contract)
        try:
            analyzer_output = run_analyzer(analyzer_input, config)
            contract = transition_status(contract, TaskStatus.complete)
            contract = contract.model_copy(update={"output": analyzer_output.model_dump()})
            aether.publish(contract)
            print(f"[vega] stage=analyzer run_id={run_id} complete")
        except Exception as e:
            contract = transition_status(contract, TaskStatus.failed)
            contract = contract.model_copy(update={"error": str(e)})
            aether.publish(contract)
            raise

        # Stage 2: Test Designer
        print(f"[vega] stage=test_designer run_id={run_id} starting")
        test_designer_input = TestDesignerInput(requirements=analyzer_output.requirements)
        contract = VegaStageRecord(
            run_id=run_id,
            stage=VegaStage.test_designer,
            status=TaskStatus.pending,
            provider=config.provider,
            model=config.model,
            input=test_designer_input.model_dump(),
        )
        aether.publish(contract)
        contract = transition_status(contract, TaskStatus.running)
        aether.publish(contract)
        try:
            test_designer_output = run_test_designer(test_designer_input, config)
            contract = transition_status(contract, TaskStatus.complete)
            contract = contract.model_copy(update={"output": test_designer_output.model_dump()})
            aether.publish(contract)
            print(f"[vega] stage=test_designer run_id={run_id} complete")
        except Exception as e:
            contract = transition_status(contract, TaskStatus.failed)
            contract = contract.model_copy(update={"error": str(e)})
            aether.publish(contract)
            raise

        # Stage 3: Bug Reporter (only if test_results provided)
        if test_results is not None:
            print(f"[vega] stage=bug_reporter run_id={run_id} starting")
            normalized_results = _normalize_test_results(test_results)
            parsed_results = [TestResult(**r) for r in normalized_results]
            bug_reporter_input = BugReporterInput(
                test_results=parsed_results,
                test_cases=test_designer_output.test_cases,
                requirements=analyzer_output.requirements,
            )
            contract = VegaStageRecord(
                run_id=run_id,
                stage=VegaStage.bug_reporter,
                status=TaskStatus.pending,
                provider=config.provider,
                model=config.model,
                input=bug_reporter_input.model_dump(),
            )
            aether.publish(contract)
            contract = transition_status(contract, TaskStatus.running)
            aether.publish(contract)
            try:
                bug_reporter_output = run_bug_reporter(bug_reporter_input, config)
                contract = transition_status(contract, TaskStatus.complete)
                contract = contract.model_copy(update={"output": bug_reporter_output.model_dump()})
                aether.publish(contract)
                print(f"[vega] stage=bug_reporter run_id={run_id} complete")
            except Exception as e:
                contract = transition_status(contract, TaskStatus.failed)
                contract = contract.model_copy(update={"error": str(e)})
                aether.publish(contract)
                raise

        outcome = "partial" if test_results is None else "success"

    finally:
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        confidence = 0.80 if outcome in ("success", "partial") else 0.0
        emitted_skill = "defect_reporting" if test_results is not None else "requirements_to_test_cases"
        try:
            feedback = RefineryFeedbackEvent(
                task_id=run_id,
                agent_id="vega",
                skill=emitted_skill,
                outcome=outcome,
                confidence_score=confidence,
                latency_ms=elapsed_ms,
            )
            aether.publish_event(FEEDBACK_STREAM, feedback.model_dump(mode="json"))
        except Exception as exc:
            print(f"[vega] warn: feedback emit failed: {exc}")
        aether.close()

    return {
        "run_id": run_id,
        "analyzer": analyzer_output.model_dump(),
        "test_designer": test_designer_output.model_dump(),
        "bug_reporter": bug_reporter_output.model_dump() if bug_reporter_output is not None else None,
    }
