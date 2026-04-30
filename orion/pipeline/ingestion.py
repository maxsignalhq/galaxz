import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis
from pydantic import ValidationError

from core.contracts import FeedbackEvent, OutcomeType, RefineryFeedbackEvent
from orion.storage.event_log import EventLog

STREAM_FEEDBACK = "aether:task.feedback"
STREAM_ESCALATED = "aether:task.escalated"
STREAM_REFINERY_VEGA = "galaxz.feedback.vega"
STREAM_REFINERY_RIGEL = "galaxz.feedback.rigel"

CONSUMER_NAME_PREFIX = "orion-worker"


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"[{ts}] [{level}] {msg}")


class IngestionWorker:
    def __init__(
        self,
        redis_url: str,
        event_log: EventLog,
        consumer_group: str = "orion-ingestion",
    ) -> None:
        self._redis_url = redis_url
        self._event_log = event_log
        self._group = consumer_group
        self._consumer_name = f"{CONSUMER_NAME_PREFIX}-{uuid4().hex[:8]}"
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._ingest_fn = None  # async (event: RefineryFeedbackEvent) -> dict

    def set_ingest_fn(self, fn) -> None:
        self._ingest_fn = fn

    async def start(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._ensure_consumer_groups()
        self._running = True
        _log("INFO", f"IngestionWorker {self._consumer_name} starting")
        await asyncio.gather(
            self._listen(STREAM_FEEDBACK, self._process_feedback),
            self._listen(STREAM_ESCALATED, self._process_escalation),
            self._listen(STREAM_REFINERY_VEGA, self._process_refinery_event),
            self._listen(STREAM_REFINERY_RIGEL, self._process_refinery_event),
        )

    async def stop(self) -> None:
        _log("INFO", "IngestionWorker stopping after current batch")
        self._running = False

    async def _ensure_consumer_groups(self) -> None:
        for stream in (
            STREAM_FEEDBACK,
            STREAM_ESCALATED,
            STREAM_REFINERY_VEGA,
            STREAM_REFINERY_RIGEL,
        ):
            try:
                await self._redis.xgroup_create(
                    stream, self._group, id="0", mkstream=True
                )
                _log("INFO", f"Created consumer group '{self._group}' on {stream}")
            except aioredis.ResponseError as exc:
                if "BUSYGROUP" in str(exc):
                    _log("INFO", f"Consumer group '{self._group}' already exists on {stream}")
                else:
                    raise

    async def _listen(self, stream: str, handler) -> None:
        # Replay pending (unACKed) messages first, then switch to new ones.
        read_id = "0"  # "0" delivers pending messages for this consumer group
        switched_to_new = False

        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer_name,
                    streams={stream: read_id},
                    count=10,
                    block=1000,
                )
            except Exception as exc:
                _log("ERROR", f"xreadgroup error on {stream}: {exc}")
                await asyncio.sleep(1)
                continue

            if not results:
                # BLOCK timeout with no messages — still running, loop again
                if not switched_to_new:
                    # Pending backlog exhausted, switch to new messages
                    read_id = ">"
                    switched_to_new = True
                    _log("INFO", f"Pending replay complete on {stream}, switching to live")
                continue

            for _stream_name, messages in results:
                for msg_id, fields in messages:
                    try:
                        await handler({"id": msg_id, "fields": fields})
                    except Exception as exc:
                        # handler must never raise, but guard here anyway
                        _log("ERROR", f"Unhandled exception in handler for {stream}/{msg_id}: {exc}")
                    finally:
                        await self._ack(stream, msg_id)

            if not switched_to_new:
                # If we got fewer than 10 pending messages, pending backlog may be done
                total_messages = sum(len(msgs) for _, msgs in results)
                if total_messages < 10:
                    read_id = ">"
                    switched_to_new = True
                    _log("INFO", f"Pending replay complete on {stream}, switching to live")

        _log("INFO", f"Listener exited for {stream}")

    async def _ack(self, stream: str, msg_id: str) -> None:
        try:
            await self._redis.xack(stream, self._group, msg_id)
        except Exception as exc:
            _log("ERROR", f"ACK failed for {stream}/{msg_id}: {exc}")

    async def _process_feedback(self, raw_message: dict) -> None:
        msg_id: str = raw_message["id"]
        fields: dict = raw_message["fields"]
        try:
            data = _decode_fields(fields)
            event = FeedbackEvent(**data)
            await self._event_log.append(event)
            _log("INFO", f"Ingested feedback event task_id={event.task_id} msg={msg_id}")
        except ValidationError as exc:
            _log("WARN", f"Validation failed for feedback msg={msg_id}: {exc}")
            await self._quarantine_raw(msg_id, fields, reason=str(exc))
        except Exception as exc:
            _log("ERROR", f"Unexpected error processing feedback msg={msg_id}: {exc}")

    async def _process_escalation(self, raw_message: dict) -> None:
        msg_id: str = raw_message["id"]
        fields: dict = raw_message["fields"]
        try:
            data = _decode_fields(fields)
            # Escalation events always carry outcome="escalated"
            data["outcome"] = OutcomeType.escalated.value
            event = FeedbackEvent(**data)
            await self._event_log.append(event)
            _log("INFO", f"Ingested escalation event task_id={event.task_id} msg={msg_id}")
        except ValidationError as exc:
            _log("WARN", f"Validation failed for escalation msg={msg_id}: {exc}")
            await self._quarantine_raw(msg_id, fields, reason=str(exc))
        except Exception as exc:
            _log("ERROR", f"Unexpected error processing escalation msg={msg_id}: {exc}")

    async def _process_refinery_event(self, raw_message: dict) -> None:
        msg_id: str = raw_message["id"]
        fields: dict = raw_message["fields"]
        try:
            data = _decode_fields(fields)
            event = RefineryFeedbackEvent(**data)
            if self._ingest_fn is None:
                _log("WARN", f"ingest_fn not set, dropping refinery event msg={msg_id}")
                return
            result = await self._ingest_fn(event)
            _log(
                "INFO",
                f"Refinery event processed task_id={event.task_id} "
                f"eligible={result['eligible']} skill={result['skill']} count={result['count']}",
            )
            count = result.get("count", 0)
            if result["eligible"] and count > 0 and count % 100 == 0:
                try:
                    await self._redis.xadd(
                        "galaxz.orion.dataset_ready",
                        {"skill": event.skill, "count": str(count)},
                    )
                    _log("INFO", f"Emitted dataset_ready skill={event.skill} count={count}")
                except Exception as exc:
                    _log("WARN", f"Failed to emit dataset_ready: {exc}")
        except ValidationError as exc:
            _log("WARN", f"Validation failed for refinery event msg={msg_id}: {exc}")
        except ValueError as exc:
            _log("WARN", f"Refinery event rejected msg={msg_id}: {exc}")
        except Exception as exc:
            _log("ERROR", f"Unexpected error processing refinery event msg={msg_id}: {exc}")

    async def _quarantine_raw(self, msg_id: str, fields: dict, reason: str) -> None:
        # We have no valid event row yet, so we write a sentinel row first,
        # then immediately quarantine it so the bad payload is traceable.
        sentinel_id = str(uuid4())
        try:
            event_id = await self._event_log.append(
                FeedbackEvent(
                    task_id=sentinel_id,
                    task_category="__invalid__",
                    agent_id="__unknown__",
                    outcome=OutcomeType.failed,
                    confidence_score=0.0,
                    input_hash="",
                    agent_output={"raw": fields},
                    latency_ms=0,
                )
            )
            await self._event_log.quarantine(event_id, f"msg_id={msg_id} | {reason}")
        except Exception as exc:
            _log("ERROR", f"Failed to write quarantine sentinel for msg={msg_id}: {exc}")


def _decode_fields(fields: dict) -> dict:
    """Redis returns all values as strings. Decode JSON-serialised fields."""
    if "data" in fields:
        # Single-envelope format (matches AetherClient publish convention)
        return json.loads(fields["data"])

    # Flat-field format: decode any value that looks like JSON
    decoded: dict = {}
    for k, v in fields.items():
        if isinstance(v, str):
            stripped = v.strip()
            if stripped and stripped[0] in ("{", "[", '"'):
                try:
                    decoded[k] = json.loads(stripped)
                    continue
                except json.JSONDecodeError:
                    pass
        decoded[k] = v
    return decoded
