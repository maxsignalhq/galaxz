import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import redis.asyncio as aioredis
import yaml

from orion.core.candidate_store import CandidateStore, FinetuneCandidate

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "finetune.yaml"
STREAM_FINETUNE = "aether:orion.finetune_candidates"


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"[{ts}] [{level}] [orion.finetune_detector] {msg}")


class FinetuneDetector:
    def __init__(
        self,
        events_db_path: str,
        candidate_store: CandidateStore,
        redis_url: str,
    ) -> None:
        self._events_db_path = events_db_path
        self._store = candidate_store
        self._redis_url = redis_url

        cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
        self._min_examples: int = int(cfg["min_examples"])
        self._min_quality_avg: float = float(cfg["min_quality_avg"])

    async def check(self) -> list[FinetuneCandidate]:
        agent_stats = await self._query_agent_stats()
        emitted: list[FinetuneCandidate] = []

        for agent_id, count, quality_avg in agent_stats:
            if count < self._min_examples or quality_avg < self._min_quality_avg:
                continue
            if self._store.has_candidate(agent_id):
                continue

            candidate = self._store.add(agent_id, count, quality_avg)
            await self._emit(candidate)
            emitted.append(candidate)
            _log(
                "INFO",
                f"fine-tune candidate emitted agent_id={agent_id} "
                f"examples={count} quality_avg={quality_avg:.3f} "
                f"candidate_id={candidate.candidate_id}",
            )

        return emitted

    async def _query_agent_stats(self) -> list[tuple[str, int, float]]:
        async with aiosqlite.connect(self._events_db_path) as db:
            cursor = await db.execute(
                """
                SELECT agent_id, COUNT(*) AS example_count, AVG(confidence) AS quality_avg
                FROM events
                WHERE quarantined = 0
                GROUP BY agent_id
                HAVING COUNT(*) > 0
                """
            )
            rows = await cursor.fetchall()
        return [(row[0], int(row[1]), float(row[2])) for row in rows]

    async def _emit(self, candidate: FinetuneCandidate) -> None:
        payload = {
            "candidate_id": candidate.candidate_id,
            "agent_id": candidate.agent_id,
            "example_count": candidate.example_count,
            "quality_avg": candidate.quality_avg,
            "emitted_at": candidate.emitted_at,
        }
        try:
            r = aioredis.from_url(self._redis_url)
            await r.xadd(STREAM_FINETUNE, {"data": json.dumps(payload)})
            await r.aclose()
        except Exception as exc:
            _log("WARN", f"Redis emit failed for candidate {candidate.candidate_id}: {exc}")
