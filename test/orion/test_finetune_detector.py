import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orion.core.candidate_store import CandidateStore
from orion.core.finetune_detector import FinetuneDetector


@pytest.fixture
def events_db(tmp_path):
    db_path = str(tmp_path / "events.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            skill_id TEXT,
            agent_id TEXT NOT NULL,
            domain TEXT,
            outcome TEXT,
            confidence REAL NOT NULL,
            human_verified INTEGER DEFAULT 0,
            payload TEXT,
            result TEXT,
            human_correction TEXT,
            latency_ms INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            quarantined INTEGER DEFAULT 0,
            exported_at TEXT
        )
    """)
    con.commit()
    con.close()
    return db_path


@pytest.fixture
def candidates_db(tmp_path):
    return str(tmp_path / "candidates.db")


@pytest.fixture
def store(candidates_db):
    return CandidateStore(candidates_db)


@pytest.fixture
def detector(events_db, store):
    return FinetuneDetector(
        events_db_path=events_db,
        candidate_store=store,
        redis_url="redis://localhost:6379",
    )


def _insert_events(db_path, agent_id, count, confidence, quarantined=0):
    con = sqlite3.connect(db_path)
    for i in range(count):
        con.execute(
            "INSERT INTO events (id, agent_id, confidence, quarantined) VALUES (?, ?, ?, ?)",
            (f"{agent_id}-{i}", agent_id, confidence, quarantined),
        )
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_emits_when_both_thresholds_met(detector, events_db):
    _insert_events(events_db, "vega", 100, 0.90)

    with patch.object(detector, "_emit", new_callable=AsyncMock) as mock_emit:
        emitted = await detector.check()

    assert len(emitted) == 1
    assert emitted[0].agent_id == "vega"
    assert emitted[0].example_count == 100
    assert mock_emit.call_count == 1


@pytest.mark.asyncio
async def test_no_emit_when_count_below_threshold(detector, events_db):
    _insert_events(events_db, "vega", 50, 0.92)

    with patch.object(detector, "_emit", new_callable=AsyncMock) as mock_emit:
        emitted = await detector.check()

    assert emitted == []
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_no_emit_when_quality_below_threshold(detector, events_db):
    _insert_events(events_db, "vega", 150, 0.70)

    with patch.object(detector, "_emit", new_callable=AsyncMock) as mock_emit:
        emitted = await detector.check()

    assert emitted == []
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_no_duplicate_candidates(detector, events_db, store):
    _insert_events(events_db, "vega", 100, 0.90)

    with patch.object(detector, "_emit", new_callable=AsyncMock):
        first = await detector.check()

    assert len(first) == 1

    with patch.object(detector, "_emit", new_callable=AsyncMock) as mock_emit:
        second = await detector.check()

    assert second == []
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_candidate_store_roundtrip(store):
    candidate = store.add("rigel", 120, 0.91)
    assert store.has_candidate("rigel")
    fetched = store.get("rigel")
    assert fetched is not None
    assert fetched.candidate_id == candidate.candidate_id
    assert fetched.agent_id == "rigel"
    assert fetched.example_count == 120
    assert abs(fetched.quality_avg - 0.91) < 1e-9


@pytest.mark.asyncio
async def test_quarantined_events_excluded(detector, events_db):
    _insert_events(events_db, "vega", 80, 0.92, quarantined=0)
    # Use a different prefix to avoid primary-key collision
    con = sqlite3.connect(events_db)
    for i in range(50):
        con.execute(
            "INSERT INTO events (id, agent_id, confidence, quarantined) VALUES (?, ?, ?, ?)",
            (f"vega-q-{i}", "vega", 0.92, 1),
        )
    con.commit()
    con.close()

    with patch.object(detector, "_emit", new_callable=AsyncMock) as mock_emit:
        emitted = await detector.check()

    # Only 80 non-quarantined events — below threshold of 100
    assert emitted == []
    mock_emit.assert_not_called()
