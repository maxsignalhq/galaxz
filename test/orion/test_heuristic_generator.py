import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from orion.pipeline.heuristic_generator import HeuristicGenerator


SEED_WEIGHTS = """version: 0
source: seed
updated_at: null
cold_start_threshold: 50

weights:
  qa.test_generation:         { vega: 1.0, rigel: 0.0 }
  qa.regression:              { vega: 1.0, rigel: 0.0 }
  qa.bug_reporting:           { vega: 1.0, rigel: 0.0 }
  rigel.skill.code_generation:{ vega: 0.0, rigel: 1.0 }
  rigel.skill.pr_review:      { vega: 0.0, rigel: 1.0 }
  rigel.skill.test_writing:   { vega: 0.2, rigel: 0.8 }
  rigel.skill.refactor:       { vega: 0.0, rigel: 1.0 }
  rigel.skill.scaffold:       { vega: 0.0, rigel: 1.0 }
  rigel.skill.debug_triage:   { vega: 0.0, rigel: 1.0 }
"""


def test_empty_events_db_skips_all_seed_skills(tmp_path):
    db_path = tmp_path / "events.db"
    weights_path = tmp_path / "routing_weights.yaml"
    _init_db(db_path)
    weights_path.write_text(SEED_WEIGHTS, encoding="utf-8")

    result = HeuristicGenerator(str(db_path), str(weights_path)).run()

    assert result["updated_skills"] == []
    assert result["drift_detected"] == []
    assert set(result["skipped_cold_start"]) == {
        "qa.test_generation",
        "qa.regression",
        "qa.bug_reporting",
        "rigel.skill.code_generation",
        "rigel.skill.pr_review",
        "rigel.skill.test_writing",
        "rigel.skill.refactor",
        "rigel.skill.scaffold",
        "rigel.skill.debug_triage",
    }


def test_run_updates_weights_after_cold_start_threshold(tmp_path):
    db_path = tmp_path / "events.db"
    weights_path = tmp_path / "routing_weights.yaml"
    _init_db(db_path)
    weights_path.write_text(SEED_WEIGHTS, encoding="utf-8")

    baseline_time = datetime.now(timezone.utc) - timedelta(days=2)
    for index in range(60):
        _insert_event(
            db_path,
            skill_id="rigel.skill.code_generation",
            agent_id="rigel",
            outcome="success",
            confidence=0.90,
            timestamp=baseline_time + timedelta(minutes=index),
        )

    generator = HeuristicGenerator(str(db_path), str(weights_path))
    analysis = generator.analyze("rigel.skill.code_generation")
    result = generator.run()
    weights = yaml.safe_load(weights_path.read_text(encoding="utf-8"))

    assert analysis["event_count"] == 60
    assert analysis["avg_confidence"] == 0.9
    assert analysis["below_cold_start_threshold"] is False
    assert result["updated_skills"] == ["rigel.skill.code_generation"]
    assert weights["version"] == 1
    assert weights["updated_at"] is not None
    assert weights["weights"]["rigel.skill.code_generation"] == {
        "rigel": 1.0,
        "vega": 0.0,
    }


def test_detect_drift_logs_warning(tmp_path, caplog):
    db_path = tmp_path / "events.db"
    weights_path = tmp_path / "routing_weights.yaml"
    _init_db(db_path)
    weights_path.write_text(SEED_WEIGHTS, encoding="utf-8")

    baseline_time = datetime.now(timezone.utc) - timedelta(days=2)
    for index in range(60):
        _insert_event(
            db_path,
            skill_id="rigel.skill.code_generation",
            agent_id="rigel",
            outcome="success",
            confidence=0.90,
            timestamp=baseline_time + timedelta(minutes=index),
        )

    current_time = datetime.now(timezone.utc) - timedelta(hours=1)
    for index in range(10):
        _insert_event(
            db_path,
            skill_id="rigel.skill.code_generation",
            agent_id="rigel",
            outcome="success",
            confidence=0.65,
            timestamp=current_time + timedelta(minutes=index),
        )

    generator = HeuristicGenerator(str(db_path), str(weights_path))
    drift = generator.detect_drift("rigel.skill.code_generation")

    with caplog.at_level(logging.WARNING):
        result = generator.run()

    assert drift == {
        "skill_id": "rigel.skill.code_generation",
        "baseline": 0.9,
        "current": 0.65,
        "drop": 0.25,
        "agent_id": "rigel",
    }
    assert result["drift_detected"] == [drift]
    assert "Drift detected: rigel/rigel.skill.code_generation dropped 0.25" in caplog.text


def _init_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE feedback_events (
                id               TEXT PRIMARY KEY,
                task_id          TEXT NOT NULL,
                task_category    TEXT NOT NULL,
                agent_id         TEXT NOT NULL,
                outcome          TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                input_hash       TEXT NOT NULL,
                agent_output     TEXT NOT NULL,
                human_correction TEXT,
                latency_ms       INTEGER NOT NULL,
                timestamp        TEXT NOT NULL,
                quarantined      INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def _insert_event(
    db_path: Path,
    *,
    skill_id: str,
    agent_id: str,
    outcome: str,
    confidence: float,
    timestamp: datetime,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO feedback_events
                (id, task_id, task_category, agent_id, outcome, confidence_score,
                 input_hash, agent_output, human_correction, latency_ms, timestamp, quarantined)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                str(uuid4()),
                str(uuid4()),
                skill_id,
                agent_id,
                outcome,
                confidence,
                uuid4().hex,
                "{}",
                None,
                100,
                timestamp.isoformat(),
            ),
        )
        conn.commit()
