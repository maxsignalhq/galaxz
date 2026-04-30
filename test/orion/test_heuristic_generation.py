import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from orion.config import OrionConfig
from orion.pipeline.heuristic_generation import HeuristicEngine, STREAM_ROUTING_UPDATE
from orion.pipeline.signal_extraction import SignalRecord
from orion.storage.dataset_store import DatasetStore
from orion.storage.event_log import EventLog
from test.conftest import TEST_REDIS_URL, make_feedback_event, redis_available


class FakeSignalExtractor:
    def __init__(self, signals):
        self.signals = signals

    async def extract_all_domains(self):
        return self.signals

    async def get_agent_trend(self, agent_id: str, days: int = 7):
        return {
            "agent_id": agent_id,
            "daily_avg_confidence": [0.9] * days,
            "trend_direction": "stable",
            "baseline_30d": 0.9,
            "current_7d": 0.9,
            "drift_delta": 0.0,
        }


@pytest_asyncio.fixture
async def redis_client():
    if not await redis_available(TEST_REDIS_URL):
        pytest.skip("Redis not available")

    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.delete(STREAM_ROUTING_UPDATE)
    yield client
    await client.delete(STREAM_ROUTING_UPDATE)
    await client.aclose()


@pytest.mark.asyncio
async def test_heuristic_engine_emits_routing_update_when_agent_leads(
    tmp_path,
    redis_client,
):
    best = make_feedback_event(
        task_category="qa.auth",
        agent_id="rigel",
        confidence_score=0.96,
    )
    second = make_feedback_event(
        task_category="qa.auth",
        agent_id="vega",
        confidence_score=0.70,
    )
    signal = SignalRecord(
        domain="qa.auth",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        total_events=2,
        completed_count=2,
        failed_count=0,
        escalated_count=0,
        corrected_count=0,
        avg_confidence=0.83,
        correction_rate=0.0,
        escalation_rate=0.0,
        high_quality_events=[best, second],
        correction_pairs=[],
    )

    engine = HeuristicEngine(
        redis_url=TEST_REDIS_URL,
        event_log=EventLog(),
        dataset_store=DatasetStore(str(tmp_path / "datasets")),
        signal_extractor=FakeSignalExtractor([signal]),
        config=OrionConfig(
            redis_url=TEST_REDIS_URL,
            routing_min_sample_size=2,
            routing_confidence_delta=0.10,
            _env_file=None,
        ),
    )

    result = await engine.run_cycle()
    messages = await redis_client.xrange(STREAM_ROUTING_UPDATE)

    assert result.routing_updates_fired == 1
    assert result.domains_analyzed == 1
    assert len(messages) == 1

    payload = json.loads(messages[0][1]["data"])
    assert payload["domain"] == "qa.auth"
    assert payload["preferred_agent"] == "rigel"
    assert "leads by" in payload["reason"]
