import json
from typing import Literal

from pydantic import BaseModel

from agents.vega.stages.analyzer import Requirement
from core.llm.provider import ProviderConfig, call_llm

SYSTEM_PROMPT = "You are a QA test design expert. You create thorough, traceable test cases from structured requirements. Each test case must link to exactly one requirement via req_id. You respond only with valid JSON. Never include markdown code fences or explanations."


class TestCase(BaseModel):
    tc_id: str
    req_id: str
    title: str
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    test_type: Literal["positive", "negative", "edge_case", "performance"]
    priority: Literal["critical", "high", "medium", "low"]
    automated: bool


class TestDesignerInput(BaseModel):
    requirements: list[Requirement]
    test_strategy: Literal["bdd", "traditional", "risk_based"] = "traditional"
    include_edge_cases: bool = True


class TestDesignerOutput(BaseModel):
    test_cases: list[TestCase]
    total_count: int
    coverage_summary: dict[str, int]
    uncovered_reqs: list[str]


def _to_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "n/a", "na"}:
            return []
        # Split common numbered/bulleted multiline output.
        parts = [p.strip(" -\t") for p in text.replace("\r", "").split("\n") if p.strip()]
        return parts if len(parts) > 1 else [text]
    return []


def _normalize_test_type(value: object) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    mapping = {
        "positive": "positive",
        "functional": "positive",
        "happy_path": "positive",
        "negative": "negative",
        "edge": "edge_case",
        "edgecase": "edge_case",
        "edge_case": "edge_case",
        "performance": "performance",
        "load": "performance",
        "stress": "performance",
    }
    return mapping.get(raw, "positive")


def _normalize_priority(value: object) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in {"critical", "high", "medium", "low"} else "medium"


def _normalize_automated(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    return raw in {"true", "1", "yes", "y", "automated"}


def _normalize_test_designer_payload(parsed: object) -> object:
    if not isinstance(parsed, dict):
        return parsed
    cases = parsed.get("test_cases")
    if not isinstance(cases, list):
        return parsed

    normalized_cases: list[dict] = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        tc = dict(item)
        tc["preconditions"] = _to_list(tc.get("preconditions"))
        tc["steps"] = _to_list(tc.get("steps"))
        tc["test_type"] = _normalize_test_type(tc.get("test_type"))
        tc["priority"] = _normalize_priority(tc.get("priority"))
        tc["automated"] = _normalize_automated(tc.get("automated"))
        normalized_cases.append(tc)

    out = dict(parsed)
    out["test_cases"] = normalized_cases
    return out


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
        for key in ("testDesignerOutput", "test_designer_output", "output", "result"):
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


def _parse_test_designer_output(text: str) -> TestDesignerOutput:
    parsed = _normalize_test_designer_payload(_unwrap_payload(_extract_json(text)))
    if _looks_like_schema(parsed):
        raise ValueError("Model returned JSON schema instead of test designer output")
    return TestDesignerOutput.model_validate(parsed)


def run_test_designer(input_data: TestDesignerInput, config: ProviderConfig) -> TestDesignerOutput:
    reqs_json = json.dumps([r.model_dump() for r in input_data.requirements], indent=2)

    user_content = (
        f"Requirements:\n{reqs_json}\n\n"
        f"Test strategy: {input_data.test_strategy}\n"
        f"Include edge cases: {input_data.include_edge_cases}\n\n"
        "Respond with ONLY a valid JSON object matching this schema — "
        "no markdown, no explanation:\n"
        + json.dumps(TestDesignerOutput.model_json_schema(), indent=2)
    )

    text, _, _ = call_llm(
        messages=[{"role": "user", "content": user_content}],
        config=config,
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        output = _parse_test_designer_output(text)
    except Exception:
        retry_content = (
            f"Requirements:\n{reqs_json}\n\n"
            f"Test strategy: {input_data.test_strategy}\n"
            f"Include edge cases: {input_data.include_edge_cases}\n\n"
            "Return ONLY a JSON object with these keys:\n"
            "- test_cases: array of objects with tc_id, req_id, title, preconditions, steps, expected_result, test_type, priority, automated\n"
            "- total_count: integer\n"
            "- coverage_summary: object map req_id -> count\n"
            "- uncovered_reqs: array of req_id strings\n\n"
            "Do NOT return JSON Schema metadata like $defs/properties/title/type."
        )
        retry_text, _, _ = call_llm(
            messages=[{"role": "user", "content": retry_content}],
            config=config,
            system_prompt=SYSTEM_PROMPT,
        )
        output = _parse_test_designer_output(retry_text)

    input_req_ids = {r.req_id for r in input_data.requirements}
    coverage_summary: dict[str, int] = {req_id: 0 for req_id in input_req_ids}
    for tc in output.test_cases:
        if tc.req_id in coverage_summary:
            coverage_summary[tc.req_id] += 1

    output = output.model_copy(update={
        "total_count": len(output.test_cases),
        "coverage_summary": coverage_summary,
        "uncovered_reqs": [req_id for req_id, count in coverage_summary.items() if count == 0],
    })

    return output
