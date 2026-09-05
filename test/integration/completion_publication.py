"""Verify durable worker evidence is visible to the API and survives recreation."""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.integration.yml"]
BASE_URL = "http://127.0.0.1:18001"


def read_json(path: str):
    with urlopen(BASE_URL + path, timeout=10) as response:
        return json.load(response)


def wait_for_review(task_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return read_json(f"/review/queue/{task_id}")
        except HTTPError as exc:
            if exc.code != 404:
                raise
        time.sleep(0.25)
    raise AssertionError("committed worker review is not visible through the API")


def main() -> None:
    # /jobs currently fixes the threshold at 0.65. Seed a normal TaskContract
    # with a strict threshold to exercise real worker escalation deterministically.
    seed = """
import os
from core.contracts import TaskContract
from core.jobs import SqliteJobRepository
task = TaskContract(origin='integration', skill='rigel.skill.code_generation',
                    payload={'spec': 'Return a deterministic integration smoke function.'},
                    confidence_threshold=1.0)
jobs = SqliteJobRepository(os.environ['JOB_DB_PATH'])
job = jobs.enqueue(task_id=task.task_id, task=task, idempotency_key=str(task.task_id))
print(job.model_dump_json())
"""
    process = subprocess.run(
        [*COMPOSE, "exec", "-T", "galaxz", "python", "-c", seed],
        cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True,
    )
    job = json.loads(process.stdout)
    review = wait_for_review(job["task_id"])
    detail = read_json(f"/jobs/{job['job_id']}")
    assert detail["job"]["status"] == "completed", detail
    assert detail["result"]["status"] == "escalated", detail
    assert review["attempt_id"] == detail["attempts"][-1]["attempt_id"]
    references = review["agent_output"]["artifact_versions"]
    assert references, review
    artifacts = detail["result"]["artifacts"]
    histories = {}
    for artifact, ref in zip(artifacts, references, strict=True):
        assert ref["content_hash"] == hashlib.sha256(artifact["content"].encode()).hexdigest()
        query = urlencode({"path": artifact["filename"], "workspace_root": ""})
        history = read_json(f"/artifacts/history?{query}")
        histories[query] = history
        assert any(row["version"] == ref["version"] and
                   row["content_hash"] == ref["content_hash"] for row in history), history

    subprocess.run([*COMPOSE, "up", "-d", "--force-recreate", "--wait", "galaxz", "worker"],
                   cwd=ROOT, check=True)
    assert wait_for_review(job["task_id"]) == review
    assert read_json(f"/jobs/{job['job_id']}")["attempts"] == detail["attempts"]
    for query, history in histories.items():
        assert read_json(f"/artifacts/history?{query}") == history
    print(f"Committed evidence for job {job['job_id']} is API-visible and survives recreation.")


if __name__ == "__main__":
    main()
