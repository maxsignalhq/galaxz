import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from agents.rigel.execution import ExecutionResult

logger = logging.getLogger(__name__)

_RIGEL_YAML = Path("config/rigel.yaml")
_DEFAULT_WEIGHTS = {"structural_check": 0.40, "self_critique": 0.40, "historical_baseline": 0.20}

_cached_weights: Optional[dict] = None


def _load_weights() -> dict:
    global _cached_weights
    if _cached_weights is not None:
        return _cached_weights
    if _RIGEL_YAML.exists():
        with open(_RIGEL_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _cached_weights = data.get("confidence", {}).get("weights", _DEFAULT_WEIGHTS)
    else:
        logger.warning("config/rigel.yaml not found — using default confidence thresholds")
        _cached_weights = _DEFAULT_WEIGHTS
    return _cached_weights


def _structural_check(skill_id: str, result: dict) -> float:
    checks = {
        "rigel.skill.code_generation": lambda r: [
            isinstance(r.get("code"), str) and len(r.get("code", "")) > 50,
            "code" in r,
        ],
        "rigel.skill.pr_review": lambda r: [
            isinstance(r.get("findings"), list),
            isinstance(r.get("summary"), str),
        ],
        "rigel.skill.test_writing": lambda r: [
            isinstance(r.get("tests"), str),
            isinstance(r.get("test_count"), int) and r.get("test_count", 0) > 0,
        ],
        "rigel.skill.refactor": lambda r: [
            bool(r.get("refactored_code")),
            isinstance(r.get("changes_made"), list),
        ],
        "rigel.skill.scaffold": lambda r: [
            isinstance(r.get("file_tree"), dict),
            isinstance(r.get("files"), list) and len(r.get("files", [])) > 0,
        ],
        "rigel.skill.debug_triage": lambda r: [
            bool(r.get("root_cause_hypothesis")),
        ],
    }

    checker = checks.get(skill_id)
    if checker is None:
        return 0.50

    results = checker(result)
    return sum(1 for v in results if v) / len(results)


def _self_critique(skill_id: str, payload: dict, result: dict, llm_client, parse_error_fallback: float = 0.75) -> dict:
    try:
        result_summary = json.dumps({k: v for k, v in result.items() if k != "code"})
    except Exception:
        result_summary = str(result)[:200]

    prompt = (
        f"Original task: {json.dumps(payload)}\n\n"
        f"Output produced (non-code fields): {result_summary}\n\n"
        "Rate whether this output fully satisfies the task.\n"
        "You MUST respond with ONLY this JSON object and nothing else — no explanation, no markdown:\n"
        '{"score": 0.85, "gaps": []}'
    )

    try:
        response = llm_client(
            system=(
                "You are a critical evaluator. "
                "You always respond with a single valid JSON object and nothing else. "
                "Never use markdown. Never add explanation outside the JSON."
            ),
            user=prompt,
        )
        parsed = json.loads(response)
        return {
            "score": float(parsed["score"]),
            "gaps": parsed.get("gaps", []),
        }
    except Exception:
        return {"score": parse_error_fallback, "gaps": ["self_critique_parse_error"]}


def score_confidence(
    skill_id: str,
    payload: dict,
    result: dict,
    llm_client,
    historical_score: float = 0.50,
    execution_result: ExecutionResult | None = None,
    parse_error_fallback: float = 0.75,
) -> dict:
    structural = _structural_check(skill_id, result)
    critique = _self_critique(skill_id, payload, result, llm_client, parse_error_fallback)
    w = _load_weights()
    soft_confidence = (
        (structural * w["structural_check"])
        + (critique["score"] * w["self_critique"])
        + (historical_score * w["historical_baseline"])
    )
    composite = _calibrated_confidence(soft_confidence, execution_result)
    return {
        "confidence": round(composite, 3),
        "soft_confidence": round(soft_confidence, 3),
        "structural": structural,
        "self_critique": critique["score"],
        "historical": historical_score,
        "execution_outcome": execution_result.outcome if execution_result is not None else None,
        "gaps": critique["gaps"],
    }


def _calibrated_confidence(
    soft_confidence: float,
    execution_result: ExecutionResult | None,
) -> float:
    if execution_result is None:
        return soft_confidence

    if execution_result.outcome == "pass":
        return 0.90 + (soft_confidence * 0.10)
    if execution_result.outcome == "fail":
        return 0.10 + (soft_confidence * 0.10)
    if execution_result.outcome == "timeout":
        return 0.05
    if execution_result.outcome == "error":
        return 0.15
    return soft_confidence
