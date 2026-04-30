from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from orion.core.weights_loader import RoutingWeightsLoader


logger = logging.getLogger(__name__)

SUCCESS_OUTCOMES = frozenset({"success", "completed", "approved"})
HUMAN_ESCALATION_OUTCOMES = frozenset({"escalated", "approved", "rejected"})
WEIGHT_TOLERANCE = 0.05
IMPROVEMENT_THRESHOLD = 0.05
DRIFT_DROP_THRESHOLD = 0.10
DEFAULT_AGENT_IDS = ("vega", "rigel")


class HeuristicGenerator:
    def __init__(self, events_db_path: str, weights_path: str):
        self.events_db_path = Path(events_db_path)
        self.weights_path = Path(weights_path)
        self.weights_loader = RoutingWeightsLoader(str(self.weights_path))
        self._weights_data = self._load_weights_data()

    def analyze(self, skill_id: str, window_hours: int = 168) -> dict:
        rows = self._query_events(skill_id, window_hours=window_hours)
        event_count = len(rows)
        avg_confidence = _mean([row["confidence_score"] for row in rows])
        success_count = sum(1 for row in rows if row["outcome"] in SUCCESS_OUTCOMES)
        escalation_count = sum(
            1
            for row in rows
            if row["outcome"] in HUMAN_ESCALATION_OUTCOMES
            or row["agent_id"] == "human_reviewer"
        )

        return {
            "skill_id": skill_id,
            "event_count": event_count,
            "avg_confidence": round(avg_confidence, 4),
            "success_rate": round(success_count / event_count, 4) if event_count else 0.0,
            "human_escalation_rate": round(escalation_count / event_count, 4) if event_count else 0.0,
            "below_cold_start_threshold": event_count < self._cold_start_threshold(),
        }

    def should_update_weights(self, skill_id: str) -> bool:
        analysis = self.analyze(skill_id)
        if analysis["event_count"] < self._cold_start_threshold():
            return False

        suggested = self._suggested_weights(skill_id)
        if not suggested:
            return False

        current = self.weights_loader.get_weights(skill_id)
        previous_avg = self._last_avg_confidence(skill_id)
        improved = analysis["avg_confidence"] - previous_avg > IMPROVEMENT_THRESHOLD

        if _weights_match(current, suggested):
            return self.weights_loader.last_version() == 0 and improved

        return improved

    def generate_weight_update(self, skill_id: str) -> dict | None:
        if not self.should_update_weights(skill_id):
            return None
        return self._suggested_weights(skill_id)

    def detect_drift(self, skill_id: str) -> dict | None:
        current_rows = self._query_events(skill_id, window_hours=24)
        baseline_rows = self._query_events(
            skill_id,
            window_hours=144,
            before_hours=24,
        )
        if not current_rows or not baseline_rows:
            return None

        current_by_agent = _group_confidence_by_agent(current_rows)
        baseline_by_agent = _group_confidence_by_agent(baseline_rows)

        strongest_drift: dict | None = None
        for agent_id, current_scores in current_by_agent.items():
            baseline_scores = baseline_by_agent.get(agent_id)
            if not baseline_scores:
                continue

            baseline = _mean(baseline_scores)
            current = _mean(current_scores)
            drop = baseline - current
            if drop <= DRIFT_DROP_THRESHOLD:
                continue

            drift = {
                "skill_id": skill_id,
                "baseline": round(baseline, 4),
                "current": round(current, 4),
                "drop": round(drop, 4),
                "agent_id": agent_id,
            }
            if strongest_drift is None or drift["drop"] > strongest_drift["drop"]:
                strongest_drift = drift

        return strongest_drift

    def run(self) -> dict:
        self.weights_loader.reload()
        self._weights_data = self._load_weights_data()

        updated_skills: list[str] = []
        drift_detected: list[dict] = []
        skipped_cold_start: list[str] = []
        updated_weights = dict(self._weights_data.get("weights", {}))
        metrics = dict(self._weights_data.get("last_update_metrics", {}))

        for skill_id in self._skill_ids():
            analysis = self.analyze(skill_id)
            if analysis["below_cold_start_threshold"]:
                skipped_cold_start.append(skill_id)

            update = self.generate_weight_update(skill_id)
            if update is not None:
                updated_weights[skill_id] = update
                updated_skills.append(skill_id)
                metrics[skill_id] = {
                    "avg_confidence": analysis["avg_confidence"],
                    "event_count": analysis["event_count"],
                }

            drift = self.detect_drift(skill_id)
            if drift is not None:
                drift_detected.append(drift)
                logger.warning(
                    "Drift detected: %s/%s dropped %.2f",
                    drift["agent_id"],
                    skill_id,
                    drift["drop"],
                )

        if updated_skills:
            self._weights_data["version"] = int(self._weights_data.get("version", 0)) + 1
            self._weights_data["source"] = "heuristic_generator"
            self._weights_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._weights_data["weights"] = updated_weights
            self._weights_data["last_update_metrics"] = metrics
            self._write_weights_data(self._weights_data)
            self.weights_loader.reload()

        return {
            "updated_skills": updated_skills,
            "drift_detected": drift_detected,
            "skipped_cold_start": skipped_cold_start,
        }

    def _query_events(
        self,
        skill_id: str,
        *,
        window_hours: int,
        before_hours: int = 0,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        window_end = now - timedelta(hours=before_hours)
        window_start = window_end - timedelta(hours=window_hours)

        where = """
            task_category = ?
            AND timestamp >= ?
            AND timestamp < ?
        """
        params: list[Any] = [
            skill_id,
            window_start.isoformat(),
            window_end.isoformat(),
        ]

        try:
            with self._connect() as conn:
                columns = _table_columns(conn, "feedback_events")
                if "quarantined" in columns:
                    where += " AND quarantined = 0"
                cursor = conn.execute(
                    f"""
                    SELECT task_category, agent_id, outcome, confidence_score, timestamp
                    FROM feedback_events
                    WHERE {where}
                    ORDER BY timestamp ASC
                    """,
                    params,
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return []
            raise

        return [
            {
                "task_category": row["task_category"],
                "agent_id": row["agent_id"],
                "outcome": row["outcome"],
                "confidence_score": float(row["confidence_score"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def _suggested_weights(self, skill_id: str) -> dict:
        rows = self._query_events(skill_id, window_hours=168)
        if not rows:
            return {}

        scores_by_agent = _group_confidence_by_agent(rows)
        agent_scores = {
            agent_id: max(_mean(scores), 0.0)
            for agent_id, scores in scores_by_agent.items()
        }

        for agent_id in self.weights_loader.get_weights(skill_id) or DEFAULT_AGENT_IDS:
            agent_scores.setdefault(agent_id, 0.0)

        total = sum(agent_scores.values())
        if total <= 0:
            equal = 1.0 / len(agent_scores)
            return {agent_id: round(equal, 4) for agent_id in sorted(agent_scores)}

        return {
            agent_id: round(score / total, 4)
            for agent_id, score in sorted(agent_scores.items())
        }

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.events_db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _cold_start_threshold(self) -> int:
        return int(self._weights_data.get("cold_start_threshold", 50))

    def _skill_ids(self) -> list[str]:
        weights = self._weights_data.get("weights", {})
        return list(weights.keys()) if isinstance(weights, dict) else []

    def _last_avg_confidence(self, skill_id: str) -> float:
        metrics = self._weights_data.get("last_update_metrics", {})
        if isinstance(metrics, dict):
            skill_metrics = metrics.get(skill_id, {})
            if isinstance(skill_metrics, dict) and "avg_confidence" in skill_metrics:
                return float(skill_metrics["avg_confidence"])
        if self.weights_loader.last_version() == 0:
            return 0.0
        return self.analyze(skill_id)["avg_confidence"]

    def _load_weights_data(self) -> dict:
        raw = self.weights_path.read_text(encoding="utf-8")
        data = yaml.safe_load(_normalize_inline_mapping_spacing(raw)) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Routing weights file must contain a mapping: {self.weights_path}")
        return data

    def _write_weights_data(self, data: dict) -> None:
        tmp_path = self.weights_path.with_suffix(".tmp")
        tmp_path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )
        tmp_path.replace(self.weights_path)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cursor.fetchall()}


def _group_confidence_by_agent(rows: list[dict]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["agent_id"]].append(row["confidence_score"])
    return grouped


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _weights_match(current: dict, suggested: dict) -> bool:
    agent_ids = set(current) | set(suggested)
    if not agent_ids:
        return False
    return all(
        abs(float(current.get(agent_id, 0.0)) - float(suggested.get(agent_id, 0.0)))
        <= WEIGHT_TOLERANCE
        for agent_id in agent_ids
    )


def _normalize_inline_mapping_spacing(raw: str) -> str:
    import re

    return re.sub(r"^(\s*[^:#\n][^:\n]*):(?=\{)", r"\1: ", raw, flags=re.MULTILINE)
