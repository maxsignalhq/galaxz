"""Submit a real task and verify its persisted result through the HTTP API."""

import json
import time
from uuid import uuid4
from urllib.request import Request
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:18001"


def read_json(path: str, payload: dict | None = None) -> dict | list:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urlopen(request, timeout=20) as response:
        assert response.status in (200, 202)
        return json.load(response)


def main() -> None:
    submitted = read_json(
        "/task",
        {
            "task": "Return a deterministic integration smoke function.",
            "skill_id": "rigel.skill.code_generation",
        },
    )
    assert isinstance(submitted, dict)
    assert submitted["status"] == "complete"
    assert "integration_smoke" in submitted["result"]["code"]

    recent = read_json("/tasks/recent")
    assert isinstance(recent, list)
    persisted = next(
        item
        for item in recent
        if item["task_id"] == submitted["task_id"] and item["status"] == "complete"
    )
    assert "integration_smoke" in json.loads(persisted["result_json"])["code"]
    print(f"Persisted task {submitted['task_id']} verified.")

    queued = read_json(
        "/jobs",
        {
            "task": "Return a deterministic integration smoke function.",
            "skill_id": "rigel.skill.code_generation",
            "idempotency_key": f"integration-{uuid4()}",
        },
    )
    assert isinstance(queued, dict)
    assert queued["status"] == "queued"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        durable = read_json(f"/jobs/{queued['job_id']}")
        assert isinstance(durable, dict)
        if durable["job"]["status"] == "completed":
            break
        if durable["job"]["status"] in ("failed", "cancelled"):
            raise AssertionError(durable)
        time.sleep(0.25)
    else:
        raise AssertionError("durable worker did not complete the job")
    assert "integration_smoke" in durable["result"]["result"]["code"]
    assert durable["attempts"][0]["worker_id"] == "integration-worker"
    print(f"Durable job {queued['job_id']} verified.")


if __name__ == "__main__":
    main()
