from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from core.contracts import FeedbackEvent, OutcomeType
from orion.storage.event_log import EventLog


class SignalRecord(BaseModel):
    domain: str
    window_start: datetime
    window_end: datetime
    total_events: int
    completed_count: int
    failed_count: int
    escalated_count: int
    corrected_count: int
    avg_confidence: float
    correction_rate: float
    escalation_rate: float
    high_quality_events: list[FeedbackEvent]
    correction_pairs: list[tuple[FeedbackEvent, dict]]


class SignalExtractor:
    def __init__(self, event_log: EventLog, window_hours: int = 24) -> None:
        self._event_log = event_log
        self._window_hours = window_hours

    async def extract(self, domain: str) -> SignalRecord:
        window_end = datetime.now(timezone.utc).replace(tzinfo=None)
        window_start = window_end - timedelta(hours=self._window_hours)

        events = await self._event_log.get_window(domain, self._window_hours)
        deduped = _deduplicate(events)

        total = len(deduped)
        completed = sum(1 for e in deduped if e.outcome == OutcomeType.completed)
        failed = sum(1 for e in deduped if e.outcome == OutcomeType.failed)
        escalated = sum(1 for e in deduped if e.outcome == OutcomeType.escalated)
        corrected = sum(1 for e in deduped if e.outcome == OutcomeType.corrected)

        avg_confidence = (
            sum(e.confidence_score for e in deduped) / total if total else 0.0
        )
        correction_rate = corrected / total if total else 0.0
        escalation_rate = escalated / total if total else 0.0

        high_quality = [
            e for e in deduped
            if e.confidence_score > 0.9 and e.human_correction is None
        ]
        correction_pairs = [
            (e, e.human_correction)
            for e in deduped
            if e.outcome == OutcomeType.corrected and e.human_correction is not None
        ]

        return SignalRecord(
            domain=domain,
            window_start=window_start,
            window_end=window_end,
            total_events=total,
            completed_count=completed,
            failed_count=failed,
            escalated_count=escalated,
            corrected_count=corrected,
            avg_confidence=round(avg_confidence, 4),
            correction_rate=round(correction_rate, 4),
            escalation_rate=round(escalation_rate, 4),
            high_quality_events=high_quality,
            correction_pairs=correction_pairs,
        )

    async def extract_all_domains(self) -> list[SignalRecord]:
        domains = await self._event_log.list_domains()
        records = []
        for domain in domains:
            record = await self.extract(domain)
            records.append(record)
        return records

    async def get_agent_trend(
        self,
        agent_id: str,
        days: int = 7,
    ) -> dict:
        events_7d = await self._event_log.get_by_agent(agent_id, days=days)
        events_30d = await self._event_log.get_by_agent(agent_id, days=30)

        current_7d = (
            sum(e.confidence_score for e in events_7d) / len(events_7d)
            if events_7d else 0.0
        )
        baseline_30d = (
            sum(e.confidence_score for e in events_30d) / len(events_30d)
            if events_30d else 0.0
        )
        drift_delta = round(current_7d - baseline_30d, 4)

        daily_avg = _daily_averages(events_7d, days)
        trend_direction = _classify_trend(daily_avg)

        return {
            "agent_id": agent_id,
            "daily_avg_confidence": daily_avg,
            "trend_direction": trend_direction,
            "baseline_30d": round(baseline_30d, 4),
            "current_7d": round(current_7d, 4),
            "drift_delta": drift_delta,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deduplicate(events: list[FeedbackEvent]) -> list[FeedbackEvent]:
    """Keep the highest-confidence event per input_hash."""
    best: dict[str, FeedbackEvent] = {}
    for event in events:
        key = event.input_hash
        if key not in best or event.confidence_score > best[key].confidence_score:
            best[key] = event
    return list(best.values())


def _daily_averages(events: list[FeedbackEvent], days: int) -> list[float]:
    """Return one average confidence per day, oldest-first, for the last N days."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    buckets: list[list[float]] = [[] for _ in range(days)]

    for event in events:
        ts = event.timestamp.replace(tzinfo=None) if event.timestamp.tzinfo else event.timestamp
        age_days = (now - ts).days
        if 0 <= age_days < days:
            # Index 0 = today, index days-1 = oldest day
            buckets[age_days].append(event.confidence_score)

    # Reverse so index 0 = oldest day (chronological order)
    daily: list[float] = []
    for bucket in reversed(buckets):
        avg = sum(bucket) / len(bucket) if bucket else 0.0
        daily.append(round(avg, 4))
    return daily


def _classify_trend(daily_avg: list[float]) -> str:
    """Simple linear trend over the daily averages."""
    populated = [v for v in daily_avg if v > 0.0]
    if len(populated) < 2:
        return "stable"

    # Compare first half mean vs second half mean
    mid = len(populated) // 2
    first_half = sum(populated[:mid]) / mid
    second_half = sum(populated[mid:]) / len(populated[mid:])
    delta = second_half - first_half

    if delta > 0.02:
        return "improving"
    if delta < -0.02:
        return "declining"
    return "stable"
