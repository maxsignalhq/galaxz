"""Organization scoping of the task log and review queue (accounts phase B2a)."""

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.state import AndromedaState
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import TaskContract
from core.jobs import SqliteJobRepository
from core.jobs.completion import CompletionPublisher


def _state(organization_id, status="complete"):
    return AndromedaState(
        task_id=str(uuid4()), origin="t", task_type="code", status=status, payload={}, required_skills=["s.k"], priority="normal",
        issued_at="2026-11-07T10:00:00+00:00", timeout_ms=1000, organization_id=organization_id,
    )


def test_task_log_is_scoped_and_status_updates_keep_the_organization(tmp_path):
    log = TaskLog(db_path=str(tmp_path / "t.db"))
    a, b = _state("org-a"), _state("org-b", "failed")
    log.write(a)
    log.write(b)
    assert log.get(a.task_id, organization_id="org-a")["organization_id"] == "org-a"
    assert log.get(a.task_id, organization_id="org-b") is None
    assert [r["task_id"] for r in log.recent(10, organization_id="org-a")] == [a.task_id]
    assert log.stats(organization_id="org-a") == {"total": 1, "complete": 1, "failed": 0, "escalated": 0}
    assert log.stats(organization_id=None)["total"] == 2
    log.update_status(a.task_id, "code", "approved")
    assert log.stats(organization_id="org-a")["total"] == 2
    assert log.stats(organization_id="org-b")["total"] == 1


def test_legacy_task_log_is_backfilled_into_default(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE tasks (task_id TEXT, task_type TEXT, assigned_agent TEXT, status TEXT, confidence REAL, "
                  "retry_count INTEGER, escalated_to_human INTEGER, failure_reason TEXT, issued_at TEXT, completed_at TEXT, "
                  "payload_json TEXT, result_json TEXT, PRIMARY KEY (task_id, status))")
        c.execute("INSERT INTO tasks VALUES ('old','code',NULL,'complete',0.9,0,0,NULL,'2026-01-01T00:00:00+00:00',NULL,'{}','{}')")
    log = TaskLog(db_path=str(path))
    assert log.get("old", organization_id="default")["organization_id"] == "default"
    assert log.get("old", organization_id="org-a") is None


def test_review_queue_is_scoped(tmp_path):
    queue = ReviewQueue(str(tmp_path / "r.db"))
    queue.enqueue(task_id="a1", task_type="c", confidence=0.4, payload={}, organization_id="org-a")
    queue.enqueue(task_id="b1", task_type="c", confidence=0.4, payload={}, organization_id="org-b")
    assert queue.get_for("a1", organization_id="org-a")["organization_id"] == "org-a"
    assert queue.get_for("a1", organization_id="org-b") is None
    assert [i["task_id"] for i in queue.get_pending(organization_id="org-a")] == ["a1"]
    assert queue.get_stats(organization_id="org-a")["pending"] == 1
    assert queue.get_stats(organization_id="org-b")["pending"] == 1
    assert len(queue.get_pending(organization_id=None)) == 2


def test_legacy_review_queue_is_backfilled_into_default(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE review_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT UNIQUE NOT NULL, task_type TEXT, "
                  "confidence REAL, payload TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, reviewed_at TEXT, reviewer_notes TEXT)")
        c.execute("INSERT INTO review_queue (task_id, task_type, confidence, payload, created_at) VALUES ('old','c',0.3,'{}','2026-01-01T00:00:00+00:00')")
    queue = ReviewQueue(str(path))
    assert queue.get_for("old", organization_id="default") is not None
    assert queue.get_for("old", organization_id="org-a") is None


def test_escalated_job_enqueues_the_review_in_the_tasks_organization(tmp_path):
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    reviews = ReviewQueue(str(tmp_path / "reviews.db"))
    task = TaskContract(origin="t", skill="rigel.skill.code_generation", payload={}, confidence_threshold=0.8, organization_id="org-a")
    job = jobs.enqueue(task_id=task.task_id, task=task, idempotency_key="k")
    _, attempt = jobs.claim(worker_id="w", lease_seconds=30)
    jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="r",
                  result={"status": "escalated", "confidence": 0.5, "result": {}, "artifacts": []})
    CompletionPublisher(jobs, ArtifactStore(str(tmp_path / "a.db")), reviews).publish_pending()
    assert reviews.get_for(str(task.task_id), organization_id="org-a") is not None
    assert reviews.get_for(str(task.task_id), organization_id="default") is None


def test_andromeda_stamps_its_escalation_and_log_with_the_tasks_organization(tmp_path):
    from test.api.test_goals_api import _build_andromeda

    andromeda = _build_andromeda(tmp_path)
    state = _state("org-a", "escalated")
    andromeda.task_log.write(state)
    assert andromeda.task_log.get(state.task_id, organization_id="org-a") is not None
