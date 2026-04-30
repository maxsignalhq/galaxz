import asyncio

import aiosqlite
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from orion import OrionService
from orion.config import OrionConfig
from orion.pipeline.ingestion import STREAM_ESCALATED, STREAM_FEEDBACK
from test.conftest import TEST_REDIS_URL, make_feedback_event, redis_available, wait_for_sqlite_count


@pytest_asyncio.fixture
async def redis_client():
    if not await redis_available(TEST_REDIS_URL):
        pytest.skip("Redis not available")

    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    for stream in (STREAM_FEEDBACK, STREAM_ESCALATED):
        await client.delete(stream)
    yield client
    for stream in (STREAM_FEEDBACK, STREAM_ESCALATED):
        await client.delete(stream)
    await client.aclose()


@pytest.mark.asyncio
async def test_orion_ingestion_worker_stays_alive_after_idle_poll(tmp_path, redis_client):
    config = OrionConfig(
        redis_url=TEST_REDIS_URL,
        db_path=str(tmp_path / "events.db"),
        dataset_path=str(tmp_path / "datasets"),
        extraction_interval_hours=999,
        heuristic_cycle_interval_hours=999,
    )
    service = OrionService(config)

    await service.start()
    try:
        await asyncio.sleep(1.2)
        assert all(not task.done() for task in service._background_tasks)

        groups = await redis_client.xinfo_groups(STREAM_FEEDBACK)
        assert groups[0]["name"] == "orion-ingestion"
        assert groups[0]["consumers"] == 1

        event = make_feedback_event(task_category="qa.idle_poll")
        await redis_client.xadd(STREAM_FEEDBACK, {"data": event.model_dump_json()})

        count = await wait_for_sqlite_count(
            config.db_path,
            "feedback_events",
            expected_count=1,
            where="quarantined = 0",
            timeout=3.0,
        )
        assert count == 1

        async with aiosqlite.connect(config.db_path) as db:
            cursor = await db.execute(
                "SELECT task_id, task_category FROM feedback_events WHERE quarantined = 0"
            )
            rows = await cursor.fetchall()

        assert rows == [(str(event.task_id), "qa.idle_poll")]
    finally:
        await service.stop()
