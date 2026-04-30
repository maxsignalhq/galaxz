import json
from typing import Literal, Optional

from pydantic import BaseModel

from agents.vega.stages.analyzer import Requirement
from agents.vega.stages.test_designer import TestCase
from core.llm.provider import ProviderConfig, call_llm

SYSTEM_PROMPT = "You are a QA bug analysis expert. You write clear, actionable bug reports from test failures. Set rigel_handoff=true for bugs that require code changes to fix. You respond only with valid JSON. Never include markdown code fences or explanations."


class TestResult(BaseModel):
    tc_id: str
    status: Literal["pass", "fail", "blocked", "skipped"]
    actual_result: Optional[str] = None
    error_log: Optional[str] = None


class BugReport(BaseModel):
    bug_id: str
    tc_id: str
    req_id: str
    title: str
    severity: Literal["critical", "major", "minor", "trivial"]
    description: str
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    suggested_fix: Optional[str] = None
    rigel_handoff: bool = False


class BugReporterInput(BaseModel):
    test_results: list[TestResult]
    test_cases: list[TestCase]
    requirements: list[Requirement]


class BugReporterOutput(BaseModel):
    bug_reports: list[BugReport]
    total_bugs: int
    critical_count: int
    rigel_handoffs: list[str]
    pass_rate: float


def _extract_json(text: str) -> object:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _unwrap_payload(parsed: object) -> object:
    if isinstance(parsed, dict):
        for key in ("bugReporterOutput", "bug_reporter_output", "output", "result"):
            candidate = parsed.get(key)
            if isinstance(candidate, dict):
                return candidate
    return parsed


def _looks_like_schema(parsed: object) -> bool:
    if not isinstance(parsed, dict):
        return False
    return "$defs" in parsed or (
        "properties" in parsed and "title" in parsed and "type" in parsed
    )


def _parse_bug_reporter_output(text: str) -> BugReporterOutput:
    parsed = _unwrap_payload(_extract_json(text))
    if _looks_like_schema(parsed):
        raise ValueError("Model returned JSON schema instead of bug reporter output")
    return BugReporterOutput.model_validate(parsed)


def run_bug_reporter(input_data: BugReporterInput, config: ProviderConfig) -> BugReporterOutput:
    total_test_count = len(input_data.test_results)
    failing = [r for r in input_data.test_results if r.status in ("fail", "blocked")]
    passing_count = sum(1 for r in input_data.test_results if r.status == "pass")
    pass_rate = passing_count / total_test_count if total_test_count > 0 else 0.0

    if not failing:
        return BugReporterOutput(
            bug_reports=[],
            total_bugs=0,
            critical_count=0,
            rigel_handoffs=[],
            pass_rate=pass_rate,
        )

    failing_tc_ids = {r.tc_id for r in failing}
    relevant_cases = [tc for tc in input_data.test_cases if tc.tc_id in failing_tc_ids]
    relevant_req_ids = {tc.req_id for tc in relevant_cases}
    relevant_reqs = [r for r in input_data.requirements if r.req_id in relevant_req_ids]

    user_content = (
        "Failing test results:\n"
        + json.dumps([r.model_dump() for r in failing], indent=2)
        + "\n\nCorresponding test cases:\n"
        + json.dumps([tc.model_dump() for tc in relevant_cases], indent=2)
        + "\n\nRelated requirements:\n"
        + json.dumps([r.model_dump() for r in relevant_reqs], indent=2)
        + "\n\nRespond with ONLY a valid JSON object matching this schema — "
        "no markdown, no explanation:\n"
        + json.dumps(BugReporterOutput.model_json_schema(), indent=2)
    )

    text, _, _ = call_llm(
        messages=[{"role": "user", "content": user_content}],
        config=config,
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        output = _parse_bug_reporter_output(text)
    except Exception:
        retry_content = (
            "Failing test results:\n"
            + json.dumps([r.model_dump() for r in failing], indent=2)
            + "\n\nCorresponding test cases:\n"
            + json.dumps([tc.model_dump() for tc in relevant_cases], indent=2)
            + "\n\nRelated requirements:\n"
            + json.dumps([r.model_dump() for r in relevant_reqs], indent=2)
            + "\n\nReturn ONLY a JSON object with keys:\n"
            "- bug_reports: array of objects with bug_id, tc_id, req_id, title, severity, description, steps_to_reproduce, expected, actual, suggested_fix, rigel_handoff\n"
            "- total_bugs: integer\n"
            "- critical_count: integer\n"
            "- rigel_handoffs: array of bug_id strings\n"
            "- pass_rate: number\n\n"
            "Do NOT return JSON Schema metadata like $defs/properties/title/type."
        )
        retry_text, _, _ = call_llm(
            messages=[{"role": "user", "content": retry_content}],
            config=config,
            system_prompt=SYSTEM_PROMPT,
        )
        output = _parse_bug_reporter_output(retry_text)
    output = output.model_copy(update={
        "total_bugs": len(output.bug_reports),
        "critical_count": sum(1 for b in output.bug_reports if b.severity == "critical"),
        "rigel_handoffs": [b.bug_id for b in output.bug_reports if b.rigel_handoff],
        "pass_rate": pass_rate,
    })

    return output
