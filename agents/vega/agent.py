import threading
from datetime import datetime, timezone
from typing import Optional

from agents.vega.pipeline import run_vega_pipeline
from core.aether.client import get_aether_client
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry

HEARTBEAT_STREAM = "galaxz.pulsar.heartbeat"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VegaAgent:
    AGENT_ID = "vega"
    AGENT_NAME = "Vega QA Agent"
    VERSION = "0.1.0"
    HEALTH_ENDPOINT = "http://vega:8080/health"

    SKILLS = {
        "requirements_to_test_cases": {
            "description": "Turn raw requirements into structured test cases.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raw_requirements": {"type": "string"},
                    "source_type": {"type": "string"},
                },
                "required": ["raw_requirements"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "test_cases": {"type": "array"},
                    "total_count": {"type": "integer"},
                },
                "required": ["test_cases", "total_count"],
            },
            "avg_confidence": 0.88,
            "avg_latency_ms": 1400,
        },
        "test_case_execution": {
            "description": "Summarize execution results for a test case run.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "test_results": {"type": "array"},
                },
                "required": ["test_results"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "total_count": {"type": "integer"},
                    "passed_count": {"type": "integer"},
                    "failed_count": {"type": "integer"},
                },
                "required": ["total_count", "passed_count", "failed_count"],
            },
            "avg_confidence": 0.74,
            "avg_latency_ms": 300,
        },
        "defect_reporting": {
            "description": "Generate defect reports from failing test execution data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "raw_requirements": {"type": "string"},
                    "test_results": {"type": ["array", "object"]},
                },
                "required": ["raw_requirements", "test_results"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "bug_reports": {"type": "array"},
                    "total_bugs": {"type": "integer"},
                },
                "required": ["bug_reports", "total_bugs"],
            },
            "avg_confidence": 0.84,
            "avg_latency_ms": 1600,
        },
    }

    def __init__(self, registry: PulsarRegistry):
        self.registry = registry
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self.registry.register(self._build_manifest())

    def _build_manifest(self) -> SkillManifest:
        return SkillManifest(
            agent_id=self.AGENT_ID,
            agent_name=self.AGENT_NAME,
            version=self.VERSION,
            skills=[
                SkillDefinition(
                    skill_id=skill_id,
                    description=skill_def["description"],
                    input_schema=skill_def["input_schema"],
                    output_schema=skill_def["output_schema"],
                    avg_confidence=skill_def["avg_confidence"],
                    avg_latency_ms=skill_def["avg_latency_ms"],
                )
                for skill_id, skill_def in self.SKILLS.items()
            ],
            health_endpoint=self.HEALTH_ENDPOINT,
            heartbeat_interval_s=30,
        )

    def start(self) -> None:
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="vega-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def stop(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1)

    def _heartbeat_loop(self) -> None:
        interval_s = self.registry.get_agent(self.AGENT_ID).heartbeat_interval_s
        while not self._heartbeat_stop.is_set():
            payload = {
                "agent_id": self.AGENT_ID,
                "timestamp": _utc_now_iso(),
                "status": "healthy",
            }
            client = get_aether_client()
            try:
                client.publish_event(HEARTBEAT_STREAM, payload)
            finally:
                client.close()
            if self._heartbeat_stop.wait(interval_s):
                break

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        context = context or {}
        if skill_id == "requirements_to_test_cases":
            result = run_vega_pipeline(
                raw_requirements=self._require_raw_requirements(payload),
                config_path=context.get("config_path", "config/providers.yaml"),
                source_type=payload.get("source_type", "plain"),
            )
            return {
                "result": result["test_designer"],
                "confidence": self.SKILLS[skill_id]["avg_confidence"],
                "artifacts": result,
            }

        if skill_id == "test_case_execution":
            normalized = self._normalize_test_results(payload.get("test_results", []))
            passed_count = sum(1 for item in normalized if item["status"] == "pass")
            failed_count = sum(1 for item in normalized if item["status"] == "fail")
            blocked_count = sum(1 for item in normalized if item["status"] == "blocked")
            return {
                "result": {
                    "total_count": len(normalized),
                    "passed_count": passed_count,
                    "failed_count": failed_count,
                    "blocked_count": blocked_count,
                    "results": normalized,
                },
                "confidence": self.SKILLS[skill_id]["avg_confidence"],
            }

        if skill_id == "defect_reporting":
            result = run_vega_pipeline(
                raw_requirements=self._require_raw_requirements(payload),
                test_results=payload.get("test_results"),
                config_path=context.get("config_path", "config/providers.yaml"),
                source_type=payload.get("source_type", "plain"),
            )
            return {
                "result": result["bug_reporter"] or {"bug_reports": [], "total_bugs": 0},
                "confidence": self.SKILLS[skill_id]["avg_confidence"],
                "artifacts": result,
            }

        raise ValueError(f"Unknown skill: {skill_id}")

    @staticmethod
    def _require_raw_requirements(payload: dict) -> str:
        value = (
            payload.get("raw_requirements")
            or payload.get("requirements")
            or payload.get("spec")
            or payload.get("task")
        )
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Vega requires 'raw_requirements' (or equivalent spec/task text)")
        return value

    @staticmethod
    def _normalize_test_results(raw: list[dict] | dict) -> list[dict]:
        if isinstance(raw, dict):
            items = raw.get("results", [])
        elif isinstance(raw, list):
            items = raw
        else:
            raise ValueError("test_results must be a list or a dict with 'results'")

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
            normalized.append(
                {
                    "tc_id": item.get("tc_id") or item.get("test_id") or item.get("id") or f"TC-{idx + 1:03d}",
                    "status": status,
                    "actual_result": item.get("actual_result") or item.get("actual"),
                    "error_log": item.get("error_log") or item.get("error"),
                }
            )
        return normalized
