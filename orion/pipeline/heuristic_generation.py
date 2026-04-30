import json
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from pydantic import BaseModel

from orion.config import DEFAULT_CONFIG, OrionConfig
from orion.pipeline.signal_extraction import SignalExtractor, SignalRecord
from orion.storage.dataset_store import DatasetStore
from orion.storage.event_log import EventLog

STREAM_ROUTING_UPDATE = "aether:routing.heuristic_update"
STREAM_DRIFT_ALERT = "aether:orion.drift_alert"
STREAM_FINE_TUNE_READY = "aether:orion.fine_tune_ready"


class HeuristicCycleResult(BaseModel):
    routing_updates_fired: int
    drift_alerts_fired: int
    fine_tune_triggers_fired: int
    domains_analyzed: int
    agents_analyzed: int
    cycle_duration_ms: int


class HeuristicEngine:
    def __init__(
        self,
        redis_url: str,
        event_log: EventLog,
        dataset_store: DatasetStore,
        signal_extractor: SignalExtractor,
        config: Optional[OrionConfig] = None,
    ) -> None:
        self._redis_url = redis_url
        self._event_log = event_log
        self._dataset_store = dataset_store
        self._extractor = signal_extractor
        self._cfg = config or DEFAULT_CONFIG
        self._redis: Optional[aioredis.Redis] = None

    async def run_cycle(self) -> HeuristicCycleResult:
        cycle_start = time.monotonic()
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

        try:
            signals = await self._extractor.extract_all_domains()
            agent_ids = _collect_agent_ids(signals)

            routing_updates = 0
            drift_alerts = 0
            fine_tune_triggers = 0

            # Step 1 — routing differentials per domain
            for signal in signals:
                fired = await self._check_routing(signal)
                routing_updates += fired

            # Step 2 — drift per agent
            for agent_id in agent_ids:
                trend = await self._extractor.get_agent_trend(agent_id)
                if _is_drifting(trend, self._cfg):
                    await self._emit_drift_alert(agent_id, trend["drift_delta"])
                    drift_alerts += 1

            # Step 3 — fine-tune thresholds per domain
            for signal in signals:
                if _has_conflicting_corrections(signal):
                    _log("INFO", f"Skipping fine-tune check for domain={signal.domain} (conflicting corrections)")
                    continue
                fired = await self._check_fine_tune(signal)
                fine_tune_triggers += fired

            cycle_ms = int((time.monotonic() - cycle_start) * 1000)

            return HeuristicCycleResult(
                routing_updates_fired=routing_updates,
                drift_alerts_fired=drift_alerts,
                fine_tune_triggers_fired=fine_tune_triggers,
                domains_analyzed=len(signals),
                agents_analyzed=len(agent_ids),
                cycle_duration_ms=cycle_ms,
            )
        finally:
            await self._redis.aclose()
            self._redis = None

    async def _check_routing(self, signal: SignalRecord) -> int:
        """Compare agents that contributed to this domain. Fire update if delta >= threshold."""
        if signal.total_events < self._cfg.routing_min_sample_size:
            return 0

        # Build per-agent confidence averages from the signal's events
        agent_scores: dict[str, list[float]] = {}
        all_events = signal.high_quality_events + [e for e, _ in signal.correction_pairs]
        for event in all_events:
            agent_scores.setdefault(event.agent_id, []).append(event.confidence_score)

        if len(agent_scores) < 2:
            return 0

        ranked = sorted(
            {aid: sum(scores) / len(scores) for aid, scores in agent_scores.items()}.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        best_agent, best_score = ranked[0]
        _, second_score = ranked[1]
        delta = round(best_score - second_score, 4)

        if delta >= self._cfg.routing_confidence_delta:
            reason = (
                f"agent {best_agent} leads by {delta:.4f} confidence "
                f"over {signal.total_events} tasks in domain={signal.domain}"
            )
            await self._emit_routing_update(signal.domain, best_agent, reason)
            return 1
        return 0

    async def _check_fine_tune(self, signal: SignalRecord) -> int:
        """Fire fine-tune trigger if correction count or correction rate threshold met."""
        stats = await self._dataset_store.get_domain_stats(signal.domain)
        correction_count = stats.get("human_correction_count", 0)

        count_threshold_met = correction_count >= self._cfg.fine_tune_correction_count
        rate_threshold_met = signal.correction_rate >= self._cfg.fine_tune_correction_rate

        if not (count_threshold_met or rate_threshold_met):
            return 0

        ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = await self._dataset_store.snapshot(signal.domain, version=ts_str)
        await self._emit_fine_tune_trigger(signal.domain, snapshot_path)
        return 1

    async def _emit_routing_update(
        self, domain: str, preferred_agent: str, reason: str
    ) -> None:
        payload = {
            "domain": domain,
            "preferred_agent": preferred_agent,
            "confidence_delta": str(self._cfg.routing_confidence_delta),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.xadd(STREAM_ROUTING_UPDATE, {"data": json.dumps(payload)})
        _log("INFO", f"routing_update domain={domain} preferred={preferred_agent}")

    async def _emit_drift_alert(self, agent_id: str, drift_delta: float) -> None:
        trend = await self._extractor.get_agent_trend(agent_id)
        payload = {
            "agent_id": agent_id,
            "baseline_30d": str(trend["baseline_30d"]),
            "current_7d": str(trend["current_7d"]),
            "drift_delta": str(drift_delta),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.xadd(STREAM_DRIFT_ALERT, {"data": json.dumps(payload)})
        _log("WARN", f"drift_alert agent={agent_id} delta={drift_delta}")

    async def _emit_fine_tune_trigger(
        self, domain: str, snapshot_path: str
    ) -> None:
        stats = await self._dataset_store.get_domain_stats(domain)
        payload = {
            "domain": domain,
            "snapshot_path": snapshot_path,
            "example_count": str(stats.get("count", 0)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.xadd(STREAM_FINE_TUNE_READY, {"data": json.dumps(payload)})
        _log("INFO", f"fine_tune_ready domain={domain} snapshot={snapshot_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_agent_ids(signals: list[SignalRecord]) -> list[str]:
    seen: set[str] = set()
    for signal in signals:
        for event in signal.high_quality_events:
            seen.add(event.agent_id)
        for event, _ in signal.correction_pairs:
            seen.add(event.agent_id)
    return list(seen)


def _is_drifting(trend: dict, cfg: OrionConfig) -> bool:
    # drift_delta is current_7d - baseline_30d; negative means confidence dropped
    return trend["drift_delta"] <= -cfg.drift_confidence_drop


def _has_conflicting_corrections(signal: SignalRecord) -> bool:
    """True if different human corrections exist for the same input_hash."""
    seen: dict[str, str] = {}
    for event, correction in signal.correction_pairs:
        correction_str = json.dumps(correction, sort_keys=True)
        if event.input_hash in seen and seen[event.input_hash] != correction_str:
            return True
        seen[event.input_hash] = correction_str
    return False


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"[{ts}] [{level}] [heuristic] {msg}")
