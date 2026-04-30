from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from core.contracts import FeedbackEvent, OutcomeType
from orion.core.dataset_store import DatasetStore
from orion.pipeline.signal_extraction import SignalRecord


logger = logging.getLogger(__name__)


class CurationResult(BaseModel):
    domain: str
    examples_added: int
    correction_examples: int
    success_examples: int
    skipped: int
    current_domain_total: int


class DatasetCurator:
    def __init__(
        self,
        dataset_store: DatasetStore,
        min_quality_score: float = 0.85,
    ) -> None:
        self._store = dataset_store
        self._min_quality = min_quality_score

    async def curate(self, signal: SignalRecord) -> CurationResult:
        correction_examples = 0
        success_examples = 0
        skipped = 0
        touched_domains: set[str] = set()

        for event, human_correction in signal.correction_pairs:
            if not event.human_verified:
                _log_skip(event.task_id, "human correction is not verified")
                skipped += 1
                continue

            domain = _domain_for_event(event)
            if domain is None:
                skipped += 1
                continue

            example = _example_for_event(
                event=event,
                domain=domain,
                completion_payload=human_correction,
                quality_weight=1.0,
            )
            if example is None:
                skipped += 1
                continue

            self._store.append_example(domain, example)
            touched_domains.add(domain)
            correction_examples += 1

        for event in signal.high_quality_events:
            if event.human_verified:
                continue
            if not _is_success(event.outcome) or event.confidence_score < 0.9:
                _log_skip(event.task_id, f"outcome={event.outcome} confidence={event.confidence_score}")
                skipped += 1
                continue

            domain = _domain_for_event(event)
            if domain is None:
                skipped += 1
                continue

            result_payload = _result_payload(event)
            example = _example_for_event(
                event=event,
                domain=domain,
                completion_payload=result_payload,
                quality_weight=event.confidence_score,
            )
            if example is None:
                skipped += 1
                continue

            self._store.append_example(domain, example)
            touched_domains.add(domain)
            success_examples += 1

        for domain in touched_domains:
            if self._store.should_flush(domain):
                path = self._store.flush(domain)
                logger.info("Dataset flush completed: %s", path)

        domain = _domain_from_signal(signal)
        current_total = self._store.stats(domain)["buffered"] if domain else 0

        return CurationResult(
            domain=domain or "unknown",
            examples_added=correction_examples + success_examples,
            correction_examples=correction_examples,
            success_examples=success_examples,
            skipped=skipped,
            current_domain_total=current_total,
        )


def _log_skip(task_id, reason: str) -> None:
    logger.info("Skipping event %s: %s", task_id, reason)


def _domain_from_signal(signal: SignalRecord) -> str | None:
    for event in signal.high_quality_events:
        domain = _domain_for_event(event)
        if domain is not None:
            return domain
    for event, _ in signal.correction_pairs:
        domain = _domain_for_event(event)
        if domain is not None:
            return domain
    return _domain_for_task_type(signal.domain, None)


def _domain_for_event(event: FeedbackEvent) -> str | None:
    domain = _domain_for_task_type(event.task_category, event.agent_id)
    if domain is None:
        logger.warning(
            "Skipping event %s: unknown dataset domain task_type=%s agent_id=%s",
            event.task_id,
            event.task_category,
            event.agent_id,
        )
    return domain


def _domain_for_task_type(task_type: str, agent_id: str | None) -> str | None:
    if task_type.startswith("qa.") or agent_id == "vega":
        return "vega"
    if task_type.startswith("rigel.") or agent_id == "rigel":
        return "rigel"
    return None


def _example_for_event(
    *,
    event: FeedbackEvent,
    domain: str,
    completion_payload: Any,
    quality_weight: float,
) -> dict | None:
    prompt_payload = _task_payload(event)
    if _is_empty_payload(prompt_payload) or _is_empty_payload(completion_payload):
        logger.info("Skipping event %s: missing payload or result", event.task_id)
        return None

    prompt = json.dumps(prompt_payload)
    completion = json.dumps(completion_payload)
    if not prompt.strip() or not completion.strip():
        logger.info("Skipping event %s: missing payload or result", event.task_id)
        return None

    return {
        "prompt": prompt,
        "completion": completion,
        "skill_id": event.task_category,
        "confidence": event.confidence_score,
        "human_verified": event.human_verified,
        "task_id": str(event.task_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "quality_weight": quality_weight,
    }


def _task_payload(event: FeedbackEvent) -> Any:
    payload = getattr(event, "task_payload", None)
    if payload is not None:
        return payload

    agent_output = event.agent_output or {}
    for key in ("task_payload", "payload", "input"):
        if key in agent_output:
            value = agent_output[key]
            return value if isinstance(value, dict) else {key: value}
    return agent_output


def _result_payload(event: FeedbackEvent) -> Any:
    payload = getattr(event, "result_payload", None)
    if payload is not None:
        return payload

    agent_output = event.agent_output or {}
    for key in ("result_payload", "result", "output"):
        if key in agent_output:
            value = agent_output[key]
            return value if isinstance(value, dict) else {key: value}
    return agent_output


def _is_empty_payload(payload: Any) -> bool:
    return payload is None or payload == "" or payload == {} or payload == []


def _is_success(outcome: OutcomeType | str) -> bool:
    value = outcome.value if isinstance(outcome, OutcomeType) else str(outcome)
    return value in {"success", "completed"}
