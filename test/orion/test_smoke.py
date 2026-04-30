"""
Smoke tests for Orion Phase 1.
Requires a running Redis instance (default: redis://localhost:6379).
Skip automatically if Redis is unavailable.

Run:  pytest test/orion/test_smoke.py -v
"""

import asyncio
import json
import os
import uuid

import aiosqlite
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from core.contracts import FeedbackEvent, OutcomeType
from orion import OrionService
from orion.config import OrionConfig

REDIS_URL = os.environ.get("ORION_REDIS_URL", "redis://localhost:6379/15")

STREAM_FEEDBACK = "aether:task.feedback"
STREAM_ESCALATED = "aether:task.escalated"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> FeedbackEvent:
    defaults = dict(
        task_id=uuid.uuid4(),
        task_category="qa.unit_test",
        agent_id="vega-v1",
        outcome=OutcomeType.completed,
        confidence_score=0.95,
        input_hash=uuid.uuid4().hex,
        agent_output={"input": "def foo(): pass", "output": "test_foo passes"},
        latency_ms=120,
    )
    defaults.update(overrides)
    return FeedbackEvent(**defaults)


async def _redis_available(url: str) -> bool:
    try:
        r = aioredis.from_url(url, socket_connect_timeout=1)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def _wait_for_rows(
    db_path: str,
    table: str,
    expected_count: int,
    timeout: float = 3.0,
    quarantined: bool = False,
) -> int:
    """Poll until the table reaches expected_count rows, return actual count."""
    deadline = asyncio.get_event_loop().time() + timeout
    where = "" if table == "quarantine_log" else f" WHERE quarantined = {1 if quarantined else 0}"
    query = f"SELECT COUNT(*) FROM {table}{where}"
    while True:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(query)
            (count,) = await cursor.fetchone()
        if count >= expected_count or asyncio.get_event_loop().time() >= deadline:
            return count
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def redis_client():
    if not await _redis_available(REDIS_URL):
        pytest.skip("Redis not available")
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    # Clean up streams before the test
    for stream in (STREAM_FEEDBACK, STREAM_ESCALATED):
        await r.delete(stream)
    yield r
    # Clean up streams after the test
    for stream in (STREAM_FEEDBACK, STREAM_ESCALATED):
        await r.delete(stream)
    await r.aclose()


@pytest_asyncio.fixture
async def orion(tmp_path, redis_client):
    """Start OrionService with isolated DB and dataset paths, stop after test."""
    config = OrionConfig(
        redis_url=REDIS_URL,
        db_path=str(tmp_path / "events.db"),
        dataset_path=str(tmp_path / "datasets"),
        # Long intervals so scheduled cycles don't fire automatically
        extraction_interval_hours=999,
        heuristic_cycle_interval_hours=999,
    )
    service = OrionService(config)
    await service.start()
    # Yield both the service and config so tests can access db_path / dataset_path
    yield service, config
    await service.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feedback_event_reaches_log(orion, redis_client):
    service, config = orion
    event = _make_event()

    await redis_client.xadd(STREAM_FEEDBACK, {"data": event.model_dump_json()})

    count = await _wait_for_rows(
        config.db_path, "feedback_events", expected_count=1, timeout=3.0
    )
    assert count == 1, f"Expected 1 non-quarantined row, got {count}"

    # Confirm the row is for our event
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT task_id, quarantined FROM feedback_events WHERE quarantined = 0"
        )
        rows = await cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == str(event.task_id)
    assert rows[0][1] == 0


@pytest.mark.asyncio
async def test_invalid_event_is_quarantined(orion, redis_client):
    service, config = orion

    # Publish a malformed payload — missing all required FeedbackEvent fields
    bad_payload = json.dumps({"garbage": "data", "not_a_valid_event": True})
    await redis_client.xadd(STREAM_FEEDBACK, {"data": bad_payload})

    # Wait for quarantine_log entry to appear
    qcount = await _wait_for_rows(
        config.db_path, "quarantine_log", expected_count=1, timeout=3.0
    )
    assert qcount == 1, f"Expected 1 quarantine_log entry, got {qcount}"

    # No valid (non-quarantined) rows in the main table
    valid_count = await _wait_for_rows(
        config.db_path, "feedback_events", expected_count=0, timeout=0.5
    )
    assert valid_count == 0, f"Expected 0 non-quarantined rows, got {valid_count}"


@pytest.mark.asyncio
async def test_high_confidence_event_produces_training_example(orion, redis_client):
    service, config = orion
    domain = "qa.unit_test"

    # Publish 5 high-confidence completed events
    events = [
        _make_event(
            task_id=uuid.uuid4(),
            input_hash=uuid.uuid4().hex,
            outcome=OutcomeType.completed,
            confidence_score=0.95,
        )
        for _ in range(5)
    ]
    for event in events:
        await redis_client.xadd(STREAM_FEEDBACK, {"data": event.model_dump_json()})

    # Wait for all 5 rows to land in the event log
    count = await _wait_for_rows(
        config.db_path, "feedback_events", expected_count=5, timeout=5.0
    )
    assert count == 5, f"Expected 5 non-quarantined rows before curation, got {count}"

    # Manually trigger extraction cycle (bypasses scheduler)
    await service.run_extraction_cycle()

    # Confirm examples were written to the dataset store (FeedbackEvent path maps to "vega")
    stats = service._dataset_store.stats("vega")
    total = stats["buffered"] + (stats["versions"] * 500 if stats["versions"] > 0 else 0)
    buffered = stats["buffered"]
    assert buffered >= 5 or stats["versions"] >= 1, (
        f"Expected >=5 buffered or >=1 flushed version for vega, got buffered={buffered} versions={stats['versions']}"
    )
