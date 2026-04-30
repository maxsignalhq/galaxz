import logging
import uuid
from typing import Callable, Optional

from agents.rigel.confidence import score_confidence
from agents.rigel.config import RigelConfig
from agents.rigel.execution import ExecutionSandboxUnavailable, execute_generated_output
from agents.rigel.skills import SKILL_REGISTRY
from core.aether.client import get_aether_client
from core.contracts import RefineryFeedbackEvent, SkillDefinition, SkillManifest
from core.llm.provider import ProviderConfig, call_llm, load_provider_config
from core.pulsar.registry import PulsarRegistry


import re as _re

logger = logging.getLogger(__name__)
FEEDBACK_STREAM = "galaxz.feedback.rigel"


def _fix_escapes(text: str) -> str:
    """Replace invalid JSON escape sequences, such as \\w, \\d, or \\s, with escaped forms."""
    # Valid JSON escapes: \" \\ \/ \b \f \n \r \t \uXXXX
    return _re.sub(r'\\([^"\\\\/bfnrtu])', r'\\\\\1', text)


def _fix_triple_quotes(text: str) -> str:
    """
    Replace Python triple-quoted strings used as JSON values with properly
    JSON-escaped single-quoted strings.
    e.g.  "code": \"\"\"...content...\"\"\"  →  "code": "...escaped..."
    """
    def escape_content(match) -> str:
        content = match.group(1)
        content = content.replace('\\', '\\\\')
        content = content.replace('"', '\\"')
        content = content.replace('\n', '\\n')
        content = content.replace('\r', '\\r')
        content = content.replace('\t', '\\t')
        return f'"{content}"'

    return _re.sub(r'"""(.*?)"""', escape_content, text, flags=_re.DOTALL)


def _extract_json(text: str) -> str:
    """
    Return the first complete JSON object found in text.
    Handles: raw JSON, ```json fences, prose with embedded JSON,
    and LLM-generated code with invalid escape sequences.
    """
    if not text:
        return text

    import json as _json

    stripped = text.strip()

    def try_parse(s: str) -> bool:
        try:
            _json.loads(s)
            return True
        except Exception:
            return False

    def try_parse_fixed(s: str):
        """Try raw → triple-quote fix → escape fix → combined."""
        if try_parse(s):
            return s
        tq = _fix_triple_quotes(s)
        if try_parse(tq):
            return tq
        fixed = _fix_escapes(s)
        if try_parse(fixed):
            return fixed
        both = _fix_escapes(tq)
        if try_parse(both):
            return both
        return None

    # Try full stripped text first
    result = try_parse_fixed(stripped)
    if result is not None:
        return result

    # Find the first { ... } block
    start = stripped.find("{")
    while start != -1:
        depth = 0
        for i, ch in enumerate(stripped[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start:i + 1]
                    result = try_parse_fixed(candidate)
                    if result is not None:
                        return result
                    break
        start = stripped.find("{", start + 1)

    return stripped


def _make_llm_client(config: ProviderConfig) -> Callable:
    def llm_client(system: str, user: str) -> str:
        text, _, _ = call_llm(
            messages=[{"role": "user", "content": user}],
            config=config,
            system_prompt=system,
        )
        return _extract_json(text) if text else ""

    return llm_client


class RigelAgent:
    AGENT_ID = "rigel"
    AGENT_NAME = "Rigel Engineering Agent"
    VERSION = "0.1.0"
    HEALTH_ENDPOINT = "http://rigel:8002/health"

    SKILLS = [
        {"skill_id": "rigel.skill.code_generation", "description": "Generate code from spec or context", "avg_confidence": 0.86, "avg_latency_ms": 900},
        {"skill_id": "rigel.skill.pr_review", "description": "Review a pull request diff for issues", "avg_confidence": 0.84, "avg_latency_ms": 700},
        {"skill_id": "rigel.skill.test_writing", "description": "Generate tests for existing code", "avg_confidence": 0.83, "avg_latency_ms": 950},
        {"skill_id": "rigel.skill.refactor", "description": "Restructure code without changing behavior", "avg_confidence": 0.81, "avg_latency_ms": 1000},
        {"skill_id": "rigel.skill.scaffold", "description": "Generate project scaffolding and boilerplate", "avg_confidence": 0.79, "avg_latency_ms": 1100},
        {"skill_id": "rigel.skill.debug_triage", "description": "Analyze errors and hypothesize root cause", "avg_confidence": 0.82, "avg_latency_ms": 650},
    ]

    def __init__(
        self,
        registry: PulsarRegistry,
        config_path: str = "config/providers.yaml",
        rigel_config: RigelConfig | None = None,
    ):
        config = load_provider_config(config_path)
        self.llm = _make_llm_client(config)
        self.registry = registry
        self.config = rigel_config or RigelConfig()
        self._register_manifest()

    def _register_manifest(self) -> None:
        self.registry.register(self._build_manifest())

    def _build_manifest(self) -> SkillManifest:
        return SkillManifest(
            agent_id=self.AGENT_ID,
            agent_name=self.AGENT_NAME,
            version=self.VERSION,
            skills=[
                SkillDefinition(
                    skill_id=skill_def["skill_id"],
                    description=skill_def["description"],
                    input_schema={},
                    output_schema={},
                    avg_confidence=skill_def["avg_confidence"],
                    avg_latency_ms=skill_def["avg_latency_ms"],
                )
                for skill_def in self.SKILLS
            ],
            health_endpoint=self.HEALTH_ENDPOINT,
            heartbeat_interval_s=30,
        )

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        handler = SKILL_REGISTRY.get(skill_id)
        if handler is None:
            raise ValueError(f"Unknown skill: {skill_id}")

        raw_result = handler(payload, self.llm)
        execution_result = None
        externally_calibrated = False
        if self.config.execution_calibration_enabled:
            try:
                execution_result = execute_generated_output(
                    skill_id=skill_id,
                    payload=payload,
                    result=raw_result,
                    timeout_s=self.config.execution_timeout_s,
                    image=self.config.execution_image,
                )
                externally_calibrated = execution_result is not None
            except ExecutionSandboxUnavailable as exc:
                logger.warning("Rigel execution calibration unavailable: %s", exc)
        confidence_data = score_confidence(
            skill_id,
            payload,
            raw_result,
            self.llm,
            execution_result=execution_result,
            parse_error_fallback=self.config.confidence_parse_error_fallback,
        )

        task_result = {
            **raw_result,
            "confidence": confidence_data["confidence"],
            "confidence_breakdown": {
                "structural": confidence_data["structural"],
                "self_critique": confidence_data["self_critique"],
                "historical": confidence_data["historical"],
                "soft_confidence": confidence_data["soft_confidence"],
                "execution_outcome": confidence_data["execution_outcome"],
            },
            "gaps": confidence_data["gaps"],
            "execution_result": (
                execution_result.model_dump(mode="python")
                if execution_result is not None
                else None
            ),
            "externally_calibrated": externally_calibrated,
        }

        self._emit_feedback(
            task_id=context.get("task_id") if context else None,
            skill_id=skill_id,
            confidence_score=confidence_data["confidence"],
            execution_outcome=confidence_data["execution_outcome"],
            latency_ms=execution_result.duration_ms if execution_result is not None else 0,
            outcome=_feedback_outcome(execution_result),
        )

        return task_result

    def health(self) -> dict:
        return {
            "agent_id": self.AGENT_ID,
            "status": "ok",
            "skills": [s["skill_id"] for s in self.SKILLS],
        }

    def _emit_feedback(
        self,
        task_id,
        skill_id: str,
        confidence_score: float,
        execution_outcome: str | None,
        latency_ms: int,
        outcome: str,
    ) -> None:
        aether = get_aether_client()
        try:
            feedback = RefineryFeedbackEvent(
                task_id=task_id or uuid.uuid4(),
                agent_id=self.AGENT_ID,
                skill=skill_id,
                outcome=outcome,
                confidence_score=confidence_score,
                execution_outcome=execution_outcome,
                latency_ms=latency_ms,
            )
            aether.publish_event(FEEDBACK_STREAM, feedback.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("Rigel feedback emit failed: %s", exc)
        finally:
            aether.close()


def _feedback_outcome(execution_result) -> str:
    if execution_result is None:
        return "success"
    if execution_result.outcome == "pass":
        return "success"
    return "fail"
