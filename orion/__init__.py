import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiofiles
import aiofiles.os

from core.contracts import (
    RefineryFeedbackEvent,
    validate_feedback_event,
)
from core.pulsar.registry import PulsarRegistry
from orion.config import OrionConfig
from orion.core.candidate_store import CandidateStore
from orion.core.dataset_store import DatasetStore as CoreDatasetStore
from orion.core.finetune_detector import FinetuneDetector
from orion.pipeline.dataset_curation import DatasetCurator
from orion.pipeline.heuristic_generator import HeuristicGenerator
from orion.pipeline.heuristic_generation import HeuristicEngine
from orion.pipeline.ingestion import IngestionWorker
from orion.pipeline.signal_extraction import SignalExtractor
from orion.storage.dataset_store import DatasetStore as StorageDatasetStore
from orion.storage.event_log import EventLog

ROUTING_WEIGHTS_PATH = "orion/config/routing_weights.yaml"

_CURATE_DOMAINS = frozenset({"vega", "rigel"})


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"[{ts}] [{level}] [orion] {msg}")


class OrionService:
    def __init__(self, config: OrionConfig, registry: PulsarRegistry | None = None) -> None:
        self._cfg = config
        self._registry = registry

        self._event_log = EventLog()
        self._dataset_store = CoreDatasetStore(config.dataset_path)
        self._heuristic_dataset_store = StorageDatasetStore(config.dataset_path)

        self._signal_extractor = SignalExtractor(
            self._event_log, window_hours=config.window_hours
        )
        self._ingestion_worker = IngestionWorker(
            redis_url=config.redis_url,
            event_log=self._event_log,
        )
        self._curator = DatasetCurator(
            dataset_store=self._dataset_store,
            min_quality_score=config.min_quality_score,
        )
        self._heuristic_engine = HeuristicEngine(
            redis_url=config.redis_url,
            event_log=self._event_log,
            dataset_store=self._heuristic_dataset_store,
            signal_extractor=self._signal_extractor,
            config=config,
        )
        self._heuristic_generator = HeuristicGenerator(
            events_db_path=config.db_path,
            weights_path=ROUTING_WEIGHTS_PATH,
        )

        _candidates_db = str(Path(config.db_path).parent / "candidates.db")
        self._candidate_store = CandidateStore(_candidates_db)
        self._finetune_detector = FinetuneDetector(
            events_db_path=config.db_path,
            candidate_store=self._candidate_store,
            redis_url=config.redis_url,
        )
        self._background_tasks: list[asyncio.Task] = []
        self._skill_counts: dict[str, int] = {}

    async def start(self) -> None:
        await self._event_log.init_db(self._cfg.db_path)
        _log("INFO", f"EventLog initialised at {self._cfg.db_path}")

        os.makedirs(self._cfg.dataset_path, exist_ok=True)
        _log("INFO", f"DatasetStore directory ready at {self._cfg.dataset_path}")

        migrated = await self._event_log.migrate_flat_jsonl(self._cfg.dataset_path)
        if migrated:
            _log("INFO", f"migrated {migrated} events from flat JSONL files into events table")

        self._ingestion_worker.set_ingest_fn(self.ingest)

        ingestion_task = asyncio.create_task(
            self._ingestion_worker.start(), name="orion-ingestion"
        )
        self._track_background_task(ingestion_task)

        extraction_task = asyncio.create_task(
            self._run_on_interval(
                self.run_extraction_cycle,
                interval_hours=self._cfg.extraction_interval_hours,
                name="extraction",
            ),
            name="orion-extraction-scheduler",
        )
        self._track_background_task(extraction_task)

        heuristic_task = asyncio.create_task(
            self._run_on_interval(
                self.run_heuristic_cycle,
                interval_hours=self._cfg.heuristic_cycle_interval_hours,
                name="heuristic",
            ),
            name="orion-heuristic-scheduler",
        )
        self._track_background_task(heuristic_task)

        heartbeat_task = asyncio.create_task(
            self._run_health_heartbeat(), name="orion-health-heartbeat"
        )
        self._track_background_task(heartbeat_task)

        _log("INFO", "Orion is watching.")

    async def run_extraction_cycle(self) -> None:
        cycle_run_id = str(uuid4())
        _log("INFO", "extraction cycle starting")
        await self._curate_from_events()
        signals = await self._signal_extractor.extract_all_domains()
        total_added = 0
        for signal in signals:
            result = await self._curator.curate(signal)
            total_added += result.examples_added
            _log(
                "INFO",
                f"curated domain={result.domain} added={result.examples_added} "
                f"corrections={result.correction_examples} "
                f"successes={result.success_examples} "
                f"skipped={result.skipped} "
                f"total={result.current_domain_total}",
            )
        _log("INFO", f"extraction cycle complete domains={len(signals)} examples_added={total_added}")
        heuristic_summary = self._heuristic_generator.run()
        _log("INFO", f"heuristic generator summary={heuristic_summary}")
        await self._finetune_detector.check()
        await self._write_health_file()

    async def run_heuristic_cycle(self) -> None:
        _log("INFO", "heuristic cycle starting")
        result = await self._heuristic_engine.run_cycle()
        _log(
            "INFO",
            f"heuristic cycle complete "
            f"routing_updates={result.routing_updates_fired} "
            f"drift_alerts={result.drift_alerts_fired} "
            f"fine_tune_triggers={result.fine_tune_triggers_fired} "
            f"domains={result.domains_analyzed} "
            f"agents={result.agents_analyzed} "
            f"duration_ms={result.cycle_duration_ms}",
        )

    async def _curate_from_events(self) -> None:
        rows = await self._event_log.get_uncurated_events()
        if not rows:
            return

        by_domain: dict[str, list[dict]] = {}
        for row in rows:
            domain = row.get("domain", "")
            if domain not in _CURATE_DOMAINS:
                continue
            by_domain.setdefault(domain, []).append(row)

        for domain, domain_rows in by_domain.items():
            curated_ids: list[str] = []
            for row in domain_rows:
                payload = json.loads(row["payload"]) if row.get("payload") else {}
                result = json.loads(row["result"]) if row.get("result") else {}
                prompt = payload.get("prompt") or (
                    f"agent={row['agent_id']} skill={row['skill_id']} task={row['task_id']}"
                )
                completion = result.get("completion") or (
                    f"outcome={row['outcome']} confidence={row['confidence']:.3f}"
                )
                example = {
                    "prompt": prompt,
                    "completion": completion,
                    "skill_id": row["skill_id"],
                    "confidence": row["confidence"],
                    "human_verified": bool(row["human_verified"]),
                    "task_id": row["task_id"],
                    "created_at": row["created_at"],
                }
                try:
                    self._dataset_store.append_example(domain, example)
                    curated_ids.append(row["id"])
                except ValueError as exc:
                    _log("WARN", f"skipping event {row['id']}: {exc}")

            if curated_ids:
                await self._event_log.mark_curated(curated_ids, domain)
                _log("INFO", f"curated {len(curated_ids)} events domain={domain}")
                if self._dataset_store.should_flush(domain):
                    path = self._dataset_store.flush(domain)
                    _log("INFO", f"dataset flushed domain={domain} path={path}")

    async def ingest(self, event: RefineryFeedbackEvent) -> dict:
        if self._registry is not None:
            manifest = self._registry.get_agent(event.agent_id)
            if manifest is None:
                raise ValueError(f"Unknown agent for refinery feedback: {event.agent_id}")
            validate_feedback_event(event, manifest)

        execution_failed = event.execution_outcome in {"fail", "timeout", "error"}
        eligible = event.human_verified or (
            event.outcome in ("success", "partial")
            and event.confidence_score >= 0.75
            and not execution_failed
        )

        if eligible:
            await self._event_log.append_event(event, quarantined=False)
            count = self._skill_counts.get(event.skill, 0) + 1
            self._skill_counts[event.skill] = count
            _log("INFO", f"ingest: stored event skill={event.skill} count={count}")
            await self._curate_from_events()
            return {"eligible": True, "skill": event.skill, "count": count}
        else:
            await self._event_log.append_event(event, quarantined=True)
            _log("INFO", f"ingest: quarantined event task_id={event.task_id} reason=low_confidence_or_not_verified")
            return {"eligible": False, "skill": event.skill, "count": 0}

    async def _run_health_heartbeat(self) -> None:
        while True:
            await self._write_health_file()
            await asyncio.sleep(120)

    async def _write_health_file(self) -> None:
        try:
            events_total = await self._count_events_total()
            buffer_vega, buffer_rigel = await self._count_unexported_buffers()
            health = {
                "status": "healthy",
                "last_cycle_at": datetime.now(timezone.utc).isoformat(),
                "events_processed_total": events_total,
                "buffer_vega": buffer_vega,
                "buffer_rigel": buffer_rigel,
            }
            health_path = Path(self._cfg.dataset_path).parent / "health.json"
            tmp_path = health_path.with_suffix(".tmp")
            async with aiofiles.open(tmp_path, mode="w", encoding="utf-8") as f:
                await f.write(json.dumps(health))
            os.replace(str(tmp_path), str(health_path))
        except Exception as exc:
            _log("ERROR", f"health file write failed: {exc}")

    async def _count_events_total(self) -> int:
        return await self._event_log.count_events()

    async def _count_unexported_buffers(self) -> tuple[int, int]:
        counts = await self._event_log.count_unexported_by_domain()
        return counts.get("vega", 0), counts.get("rigel", 0)

    async def stop(self) -> None:
        _log("INFO", "Orion stopping")
        await self._ingestion_worker.stop()
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._background_tasks.clear()
        _log("INFO", "Orion stopped")

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.append(task)
        task.add_done_callback(self._log_background_task_result)

    @staticmethod
    def _log_background_task_result(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _log("ERROR", f"background task {task.get_name()} exited: {exc}")

    @staticmethod
    async def _run_on_interval(coro_fn, interval_hours: int, name: str) -> None:
        interval_secs = interval_hours * 3600
        while True:
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log("ERROR", f"{name} cycle failed: {exc}")
            await asyncio.sleep(interval_secs)


def _preferred_quality_score(event: RefineryFeedbackEvent, execution_passed: bool) -> float:
    if event.human_verified:
        return 1.0
    if execution_passed:
        return max(event.confidence_score, 0.95)
    if event.execution_outcome is None:
        return min(event.confidence_score, 0.89)
    return event.confidence_score
