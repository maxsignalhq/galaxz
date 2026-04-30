import json
from typing import Literal, Optional

from pydantic import BaseModel

from core.llm.provider import ProviderConfig, call_llm

SYSTEM_PROMPT = "You are a QA requirements analyst. You extract and structure software requirements from raw documentation. You respond only with valid JSON. Never include markdown code fences or explanations in your response."


class Requirement(BaseModel):
    req_id: str
    title: str
    description: str
    category: Literal["functional", "non_functional", "edge_case"]
    priority: Literal["critical", "high", "medium", "low"]
    testable: bool
    ambiguity_flag: bool
    ambiguity_note: Optional[str] = None


class AnalyzerInput(BaseModel):
    raw_requirements: str
    source_type: Literal["markdown", "plain"] = "plain"
    context: Optional[str] = None


class AnalyzerOutput(BaseModel):
    requirements: list[Requirement]
    total_count: int
    ambiguous_count: int
    untestable_count: int
    summary: str


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
        for key in ("analyzerOutput", "analyzer_output", "output", "result"):
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


def _parse_analyzer_output(text: str) -> AnalyzerOutput:
    parsed = _unwrap_payload(_extract_json(text))
    if _looks_like_schema(parsed):
        raise ValueError("Model returned JSON schema instead of analyzer output")
    return AnalyzerOutput.model_validate(parsed)


def run_analyzer(input_data: AnalyzerInput, config: ProviderConfig) -> AnalyzerOutput:
    user_content = f"Requirements:\n{input_data.raw_requirements}"
    if input_data.context:
        user_content += f"\n\nContext:\n{input_data.context}"
    user_content += (
        "\n\nRespond with ONLY a valid JSON object matching this schema — "
        "no markdown, no explanation:\n"
        + json.dumps(AnalyzerOutput.model_json_schema(), indent=2)
    )

    text, _, _ = call_llm(
        messages=[{"role": "user", "content": user_content}],
        config=config,
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        output = _parse_analyzer_output(text)
    except Exception:
        retry_content = (
            f"Requirements:\n{input_data.raw_requirements}\n\n"
            "Return ONLY a JSON object with these top-level keys:\n"
            "- requirements: array of objects with req_id, title, description, category, priority, testable, ambiguity_flag, ambiguity_note\n"
            "- total_count: integer\n"
            "- ambiguous_count: integer\n"
            "- untestable_count: integer\n"
            "- summary: string\n\n"
            "Do NOT return JSON Schema metadata like $defs/properties/title/type."
        )
        retry_text, _, _ = call_llm(
            messages=[{"role": "user", "content": retry_content}],
            config=config,
            system_prompt=SYSTEM_PROMPT,
        )
        output = _parse_analyzer_output(retry_text)
    output = output.model_copy(update={
        "total_count": len(output.requirements),
        "ambiguous_count": sum(1 for r in output.requirements if r.ambiguity_flag),
        "untestable_count": sum(1 for r in output.requirements if not r.testable),
    })

    return output
