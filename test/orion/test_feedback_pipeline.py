import pytest
import pytest_asyncio
import aiosqlite

from core.contracts import RefineryFeedbackEvent
from orion import OrionService
from orion.config import OrionConfig


def _make_event(**overrides) -> RefineryFeedbackEvent:
    defaults = {
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "agent_id": "vega",
        "skill": "requirements_to_test_cases",
        "outcome": "success",
        "confidence_score": 0.9,
        "human_verified": False,
        "latency_ms": 450,
    }
    defaults.update(overrides)
    return RefineryFeedbackEvent(**defaults)


@pytest_asyncio.fixture
async def orion_service(tmp_path):
    config = OrionConfig(
        redis_url="redis://localhost:6379",
        db_path=str(tmp_path / "events.db"),
        dataset_path=str(tmp_path / "datasets"),
    )
    svc = OrionService(config)
    await svc._event_log.init_db(config.db_path)
    return svc


async def _fetch_events(db_path: str, quarantined: int = 0) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM events WHERE quarantined = ?", (quarantined,)
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@pytest.mark.asyncio
async def test_eligible_event_written_to_events_table(tmp_path, monkeypatch, orion_service):
    monkeypatch.chdir(tmp_path)
    event = _make_event()

    result = await orion_service.ingest(event)

    assert result["eligible"] is True
    assert result["skill"] == "requirements_to_test_cases"
    assert result["count"] == 1

    rows = await _fetch_events(str(tmp_path / "events.db"), quarantined=0)
    assert len(rows) == 1
    row = rows[0]
    assert row["skill_id"] == "requirements_to_test_cases"
    assert row["domain"] == "vega"
    assert row["outcome"] == "success"
    assert row["confidence"] == pytest.approx(0.9)
    assert row["quarantined"] == 0


@pytest.mark.asyncio
async def test_low_confidence_event_quarantined(tmp_path, monkeypatch, orion_service):
    monkeypatch.chdir(tmp_path)
    event = _make_event(confidence_score=0.3, outcome="fail")

    result = await orion_service.ingest(event)

    assert result["eligible"] is False

    rows = await _fetch_events(str(tmp_path / "events.db"), quarantined=1)
    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == str(event.task_id)
    assert row["confidence"] == pytest.approx(0.3)
    assert row["quarantined"] == 1


@pytest.mark.asyncio
async def test_human_verified_bypasses_confidence_threshold(tmp_path, monkeypatch, orion_service):
    monkeypatch.chdir(tmp_path)
    event = _make_event(confidence_score=0.2, human_verified=True, outcome="fail")

    result = await orion_service.ingest(event)

    assert result["eligible"] is True

    rows = await _fetch_events(str(tmp_path / "events.db"), quarantined=0)
    assert len(rows) == 1
    assert rows[0]["human_verified"] == 1


@pytest.mark.asyncio
async def test_skill_counter_increments_per_skill(tmp_path, monkeypatch, orion_service):
    monkeypatch.chdir(tmp_path)

    for _ in range(3):
        await orion_service.ingest(_make_event(skill="requirements_to_test_cases"))
    await orion_service.ingest(_make_event(skill="defect_reporting"))

    assert orion_service._skill_counts["requirements_to_test_cases"] == 3
    assert orion_service._skill_counts["defect_reporting"] == 1


@pytest.mark.asyncio
async def test_two_distinct_events_both_stored(tmp_path, monkeypatch, orion_service):
    monkeypatch.chdir(tmp_path)

    await orion_service.ingest(_make_event(confidence_score=0.96))
    await orion_service.ingest(
        _make_event(
            task_id="550e8400-e29b-41d4-a716-446655440001",
            confidence_score=0.91,
            execution_outcome="pass",
        )
    )

    rows = await _fetch_events(str(tmp_path / "events.db"), quarantined=0)
    assert len(rows) == 2
