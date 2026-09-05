"""Kill a worker mid-attempt and verify lease-based recovery end to end."""

import json
import subprocess
import time
from pathlib import Path
from urllib.request import Request
from urllib.request import urlopen
from uuid import uuid4


BASE_URL = "http://127.0.0.1:18001"
ROOT = Path(__file__).parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.integration.yml"]


def read_json(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def wait_for_status(job_id: str, statuses: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = read_json(f"/jobs/{job_id}")
        if detail["job"]["status"] in statuses:
            return detail
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], cwd=ROOT, check=True)


def main() -> None:
    queued = read_json(
        "/jobs",
        {
            "task": "Run the durable crash recovery integration scenario.",
            "skill_id": "rigel.skill.code_generation",
            "idempotency_key": f"crash-recovery-{uuid4()}",
            "retry_policy": {
                "max_attempts": 2,
                "backoff_seconds": 0,
                "max_backoff_seconds": 0,
            },
        },
    )
    job_id = queued["job_id"]
    wait_for_status(job_id, {"running"}, 10)
    compose("stop", "-t", "0", "worker")
    compose("stop", "-t", "0", "galaxz")
    compose("up", "--wait", "galaxz")
    time.sleep(12)
    compose("up", "-d", "worker")
    detail = wait_for_status(job_id, {"completed", "failed"}, 60)

    assert detail["job"]["status"] == "completed", detail
    assert len(detail["attempts"]) == 2
    assert detail["attempts"][0]["outcome"] == "lease_expired"
    assert detail["attempts"][1]["outcome"] == "completed"
    assert [transition["reason"] for transition in detail["transitions"]].count(
        "completed"
    ) == 1
    assert "integration_smoke" in detail["result"]["result"]["code"]
    print(f"Recovered durable job {job_id} without duplicate completion.")


if __name__ == "__main__":
    main()
