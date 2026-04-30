import asyncio
import os
import uuid
from datetime import datetime, timezone

import aiosqlite
import pytest
import redis.asyncio as aioredis

from core.contracts import FeedbackEvent, OutcomeType

TEST_REDIS_URL = os.environ.get("ORION_REDIS_URL", "redis://localhost:6379/15")


def make_feedback_event(**overrides) -> FeedbackEvent:
    defaults = {
        "task_id": uuid.uuid4(),
        "task_category": "qa.unit_test",
        "agent_id": "vega",
        "outcome": OutcomeType.completed,
        "confidence_score": 0.95,
        "input_hash": uuid.uuid4().hex,
        "agent_output": {"input": "def add(a, b): return a + b", "output": "test_add passes"},
        "latency_ms": 120,
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return FeedbackEvent(**defaults)


async def redis_available(url: str) -> bool:
    try:
        client = aioredis.from_url(url, socket_connect_timeout=1)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.fixture
def deterministic_rigel_llm():
    def llm(system: str, user: str) -> str:
        if "Rate whether this output fully satisfies the task" in user:
            return '{"score": 0.92, "gaps": []}'
        if "root_cause_hypothesis" in user:
            return (
                '{"root_cause_hypothesis": "Input validation accepts invalid values", '
                '"confidence": 0.88, "suggested_fix_approach": "Add boundary validation", '
                '"next_step": "code_generation"}'
            )
        if '"findings"' in user:
            return (
                '{"findings": [{"severity": "high", "file": "app.py", "line": 12, '
                '"issue": "Missing validation", "suggestion": "Reject invalid input"}], '
                '"summary": "Validation gap found", "approved": false}'
            )
        if '"file_tree"' in user:
            return (
                '{"file_tree": {"app.py": "file"}, '
                '"files": [{"path": "app.py", "content": "print(\\"ok\\")"}], '
                '"instructions": "Run python app.py"}'
            )
        if "Write pytest tests" in user:
            return "def test_add():\n    assert add(1, 2) == 3\n"
        if "Refactor the following" in user:
            return "def add(a, b):\n    return a + b\n"
        return (
            "def generated(value):\n"
            "    if value is None:\n"
            "        raise ValueError('value is required')\n"
            "    return {'value': value, 'status': 'ok'}\n"
        )

    return llm


async def wait_for_sqlite_count(
    db_path: str,
    table: str,
    expected_count: int,
    where: str = "",
    timeout: float = 3.0,
) -> int:
    deadline = asyncio.get_event_loop().time() + timeout
    query = f"SELECT COUNT(*) FROM {table}"
    if where:
        query += f" WHERE {where}"

    while True:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(query)
            (count,) = await cursor.fetchone()
        if count >= expected_count or asyncio.get_event_loop().time() >= deadline:
            return count
        await asyncio.sleep(0.1)
