from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import sqlite3
from uuid import uuid4

import pytest

from agents.andromeda.review_queue import ReviewQueue
from core.artifacts.store import ArtifactStore
from core.contracts import JobStatus
from core.contracts import TaskContract
from core.jobs import SqliteJobRepository
from core.jobs import InvalidJobState
from core.jobs import LeaseConflict
from core.jobs.completion import CompletionPublisher


@pytest.fixture
def completion(tmp_path):
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    artifacts = ArtifactStore(str(tmp_path / "artifacts.db"))
    reviews = ReviewQueue(str(tmp_path / "reviews.db"))
    task = TaskContract(origin="test", skill="rigel.skill.code_generation", payload={},
                        confidence_threshold=0.8)
    job = jobs.enqueue(task_id=task.task_id, task=task, idempotency_key="completion")
    _, attempt = jobs.claim(worker_id="worker", lease_seconds=30)
    result = {
        "status": "escalated", "confidence": 0.5, "assigned_agent": "rigel",
        "result": {"summary": "review this"},
        "artifacts": [{"filename": "a.py", "content": "first"}],
    }
    return jobs, artifacts, reviews, job, attempt, result


def finish(fixture):
    jobs, _, _, job, attempt, result = fixture
    return jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token,
                         output_ref="result", result=result)


def test_completion_publishes_only_committed_evidence_and_replays(completion):
    jobs, artifacts, reviews, job, attempt, result = completion
    publisher = CompletionPublisher(jobs, artifacts, reviews)
    publisher.publish_pending()
    assert reviews.get_pending() == []
    assert artifacts.list_files() == []
    finish(completion)
    finish(completion)
    publisher.publish_pending()
    publisher.publish_pending()
    review = reviews.get_by_task_id(str(job.task_id))
    assert review["attempt_id"] == str(attempt.attempt_id)
    ref = review["agent_output"]["artifact_versions"][0]
    assert artifacts.get_version(ref["identity_key"], ref["version"])["content"] == "first"
    assert len(reviews.get_pending()) == 1
    assert jobs.pending_completions() == []


@pytest.mark.parametrize("boundary", ["artifact", "review", "ack"])
def test_failed_publication_is_recoverable(completion, monkeypatch, boundary):
    jobs, artifacts, reviews, job, attempt, result = completion
    finish(completion)
    target, method = {"artifact": (artifacts, "record"), "review": (reviews, "enqueue"),
                      "ack": (jobs, "acknowledge_completion")}[boundary]
    original = getattr(target, method)

    def fail(*args, **kwargs):
        raise OSError("injected storage failure")

    monkeypatch.setattr(target, method, fail)
    CompletionPublisher(jobs, artifacts, reviews).publish_pending()
    assert jobs.get_job(job.job_id).status is JobStatus.completed
    assert len(jobs.pending_completions()) == 1
    if boundary != "ack":
        assert reviews.get_pending() == []
    if boundary == "artifact":
        assert artifacts.list_files() == []
    monkeypatch.setattr(target, method, original)
    # Reopen the durable queue to simulate restart.
    restarted = SqliteJobRepository(jobs.database)
    CompletionPublisher(restarted, artifacts, reviews).publish_pending()
    assert len(reviews.get_pending()) == 1
    assert len(artifacts.history("::a.py")) == 1
    assert restarted.pending_completions() == []


def test_completion_transaction_rolls_back_outbox_and_result(completion, monkeypatch):
    jobs, artifacts, reviews, job, attempt, result = completion
    original = jobs._record_transition

    def fail(*args, **kwargs):
        raise OSError("database failure before commit")

    monkeypatch.setattr(jobs, "_record_transition", fail)
    with pytest.raises(OSError):
        finish(completion)
    assert jobs.get_job(job.job_id).status is JobStatus.running
    assert jobs.get_result(job.job_id) is None
    assert jobs.pending_completions() == []
    monkeypatch.setattr(jobs, "_record_transition", original)
    finish(completion)
    assert len(jobs.pending_completions()) == 1


def test_concurrent_publishers_do_not_duplicate_versions(completion):
    jobs, artifacts, reviews, job, attempt, result = completion
    finish(completion)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(CompletionPublisher(jobs, artifacts, reviews).publish_pending)
                   for _ in range(2)]
        for future in futures:
            future.result()
    assert len(reviews.get_pending()) == 1
    assert len(artifacts.history("::a.py")) == 1


def test_deduplicated_attempt_keeps_original_version_after_other_write(completion):
    _, artifacts, _, _, attempt, _ = completion
    kwargs = dict(workspace_root="", task_id="task", skill="skill")
    artifacts.record([{"filename": "a.py", "content": "first"}], **kwargs)
    first = artifacts.record([{"filename": "a.py", "content": "first"}],
                             attempt_id=str(attempt.attempt_id), **kwargs)
    artifacts.record([{"filename": "a.py", "content": "second"}], **kwargs)
    replay = artifacts.record([{"filename": "a.py", "content": "first"}],
                              attempt_id=str(attempt.attempt_id), **kwargs)
    assert replay == first
    assert len(artifacts.history("::a.py")) == 2


def test_artifact_batch_failure_does_not_publish_partial_versions(completion):
    _, artifacts, _, _, attempt, _ = completion
    with pytest.raises(KeyError):
        artifacts.record([{"filename": "a.py", "content": "first"}, {"filename": "b.py"}],
                         workspace_root="", task_id="task", skill="skill",
                         attempt_id=str(attempt.attempt_id))
    assert artifacts.list_files() == []


def test_expired_completion_cannot_publish_evidence(completion):
    jobs, artifacts, reviews, job, attempt, result = completion
    with pytest.raises(LeaseConflict):
        jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token,
                      output_ref="result", result=result,
                      now=datetime.now(timezone.utc) + timedelta(minutes=1))
    CompletionPublisher(jobs, artifacts, reviews).publish_pending()
    assert jobs.pending_completions() == []
    assert artifacts.list_files() == []
    assert reviews.get_pending() == []


def test_retried_completion_rejects_changed_evidence(completion):
    jobs, _, _, job, attempt, result = completion
    finish(completion)
    with pytest.raises(InvalidJobState):
        jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token,
                      output_ref="result", result={**result, "artifacts": []})
    assert jobs.get_result(job.job_id) == result


def test_durable_routing_defers_artifacts_and_reviews(tmp_path):
    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.task_log import TaskLog
    from core.contracts import SkillDefinition
    from core.contracts import SkillManifest
    from core.pulsar.registry import PulsarRegistry

    class Agent:
        def run(self, skill_id, payload, context):
            return {"confidence": 0.7, "result": {
                "artifacts": [{"filename": "a.py", "content": "first"}]}}

    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(SkillManifest(
        agent_id="fake", agent_name="Fake", version="1.0.0", health_endpoint="/health",
        skills=[SkillDefinition(skill_id="fake.skill.echo", description="echo",
                                input_schema={}, output_schema={})]))
    artifacts = ArtifactStore(str(tmp_path / "artifacts.db"))
    reviews = ReviewQueue(str(tmp_path / "reviews.db"))
    router = Andromeda(registry=registry, agents={"fake": Agent()},
                       task_log=TaskLog(str(tmp_path / "tasks.db")),
                       artifact_store=artifacts, review_queue=reviews)
    task = TaskContract(origin="test", skill="fake.skill.echo", payload={},
                        confidence_threshold=0.9, execution_attempt_id=uuid4())
    result = router.route(task=task)
    assert result["status"] == "escalated"
    assert result["artifacts"]
    assert artifacts.list_files() == []
    assert reviews.get_pending() == []
    # The synchronous migration path still publishes immediately.
    router.route(task=task.model_copy(update={"execution_attempt_id": None}))
    assert len(artifacts.list_files()) == 1
    assert len(reviews.get_pending()) == 1


def test_populated_v1_upgrade_preserves_job_and_adds_completion_outbox(tmp_path):
    from core.jobs.migrations import upgrade

    database = tmp_path / "jobs.db"
    with sqlite3.connect(database) as connection:
        upgrade(connection, target=1)
    old = SqliteJobRepository(database, migrate=False)
    task = TaskContract(origin="test", skill="fake.skill.echo", payload={},
                        confidence_threshold=0.8)
    job = old.enqueue(task_id=task.task_id, task=task, idempotency_key="upgrade")
    current = SqliteJobRepository(database)
    assert current.migration_version() == 2
    assert current.get_job(job.job_id) == job
    assert current.get_task(job.job_id) == task
    _, attempt = current.claim(worker_id="worker", lease_seconds=30)
    current.complete(job_id=job.job_id, lease_token=attempt.lease_token,
                     output_ref="result", result={"status": "escalated"})
    assert current.pending_completions()[0]["attempt_id"] == str(attempt.attempt_id)


def test_conflicting_review_is_not_acknowledged(completion):
    jobs, artifacts, reviews, job, attempt, result = completion
    reviews.enqueue(task_id=str(job.task_id), task_type="test", confidence=0.2,
                    payload={}, attempt_id=str(uuid4()))
    finish(completion)
    CompletionPublisher(jobs, artifacts, reviews).publish_pending()
    assert len(jobs.pending_completions()) == 1
