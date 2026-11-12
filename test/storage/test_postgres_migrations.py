import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from core.storage.manage import SchemaVersionError
from core.storage.manage import database_engine
from core.storage.manage import migrate
from core.storage.manage import migration_config
from core.storage.manage import require_current_schema
from core.jobs.postgres_repository import PostgresJobRepository
from core.contracts import TaskContract
from core.artifacts.object_storage import LocalObjectStorage
from core.storage.postgres_shared import PostgresArtifactStore


@pytest.fixture
def database():
    url = os.getenv("GALAXZ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Run docker compose -f docker-compose.postgres-test.yml run --build --rm migration-tests")
    # Each test owns only its randomly named schema, never existing application tables.
    schema = "test_" + uuid4().hex
    admin = database_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = database_engine(isolated_url.render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_fresh_upgrade_is_explicit_and_repeatable(database):
    with database.connect() as connection:
        with pytest.raises(SchemaVersionError, match="uninitialized"):
            require_current_schema(connection)
        assert inspect(connection).get_table_names() == []
    migrate(database)
    migrate(database)
    with database.connect() as connection:
        require_current_schema(connection)
        assert {
            "goals", "projects", "planned_tasks", "tasks", "goal_events", "jobs",
            "execution_attempts", "job_transitions", "job_tasks", "job_outputs",
            "job_idempotency", "review_queue", "artifact_versions",
            "completion_outbox", "artifact_attempt_versions",
        } <= set(inspect(connection).get_table_names())


def test_populated_baseline_upgrade_preserves_evidence(database):
    migrate(database, "0001_operational")
    with database.begin() as connection:
        connection.exec_driver_sql("""
            INSERT INTO goals VALUES ('goal', 'test', 'objective', 0.8, 'running', 0.9, '2026-09-04');
            INSERT INTO projects VALUES ('project', 'goal', 'title', 'description', 0);
            INSERT INTO planned_tasks (task_id, project_id, goal_id, skill, payload_json)
                VALUES ('task', 'project', 'goal', 'echo', '{}');
            INSERT INTO goal_events (goal_id, actor, action, created_at)
                VALUES ('goal', 'operator', 'resume', '2026-09-04');
            INSERT INTO jobs (job_id, task_id, status, priority, max_attempts, backoff_seconds,
                max_backoff_seconds, retryable_outcomes_json, created_at, updated_at, available_at)
                VALUES ('job', 'task', 'completed', 0, 1, 0, 0, '[]', 'now', 'now', 'now');
            INSERT INTO execution_attempts (attempt_id, job_id, attempt_number, worker_id,
                input_ref, lease_token, lease_expires_at, started_at, ended_at, outcome)
                VALUES ('attempt', 'job', 1, 'worker', 'input', 'token', 'later', 'now', 'now', 'completed');
            INSERT INTO job_outputs VALUES ('job', '{"status":"escalated"}', 'now');
            INSERT INTO artifact_versions (identity_key, version, content, content_hash, filename,
                task_id, skill, created_at, attempt_artifact_key)
                VALUES ('::a.py', 1, 'print(1)', 'hash', 'a.py', 'task', 'echo', 'now', 'attempt::::a.py');
            INSERT INTO review_queue (task_id, agent_output, created_at, attempt_id)
                VALUES ('task', '{"code":"print(1)"}', 'now', 'attempt');
        """)
        tables = inspect(connection).get_table_names()
        before = {t: connection.exec_driver_sql(f'SELECT * FROM "{t}"').fetchall()
                  for t in tables if t != "alembic_version"}
        with pytest.raises(SchemaVersionError, match="0001_operational"):
            require_current_schema(connection)
    migrate(database)
    with database.connect() as connection:
        require_current_schema(connection)
        for table, rows in before.items():
            after = connection.exec_driver_sql(f'SELECT * FROM "{table}"').fetchall()
            # Later migrations may append columns; the original columns must be preserved.
            width = len(rows[0]) if rows else 0
            assert [tuple(row[:width]) for row in after] == rows
        assert connection.exec_driver_sql("SELECT * FROM artifact_attempt_versions").fetchall() == [
            ("attempt::::a.py", "::a.py", 1)]
        assert connection.exec_driver_sql("SELECT * FROM completion_outbox").fetchall() == []


def test_unknown_revision_is_rejected_without_mutation(database):
    migrate(database)
    with database.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'future_revision'")
    with database.connect() as connection:
        with pytest.raises(SchemaVersionError, match="matching Galaxz release"):
            require_current_schema(connection)
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "future_revision"


def test_failed_upgrade_rolls_back_ddl_and_version(database):
    migrate(database, "0001_operational")
    with database.begin() as connection:
        # The second CREATE in v2 will fail after the first has executed.
        connection.exec_driver_sql("CREATE TABLE artifact_attempt_versions (sentinel TEXT)")
        connection.exec_driver_sql("INSERT INTO artifact_attempt_versions VALUES ('keep')")
    with pytest.raises(Exception):
        migrate(database)
    with database.connect() as connection:
        assert "completion_outbox" not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0001_operational"
        assert connection.exec_driver_sql("SELECT sentinel FROM artifact_attempt_versions").scalar() == "keep"


def test_concurrent_migrators_serialize(database):
    environment = {
        **os.environ,
        "GALAXZ_DATABASE_URL": database.url.render_as_string(hide_password=False),
    }

    def run_migration():
        result = subprocess.run(
            [sys.executable, "-m", "core.storage.manage", "upgrade"],
            env=environment, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_migration) for _ in range(2)]
        for future in futures:
            future.result()
    with database.connect() as connection:
        require_current_schema(connection)


def test_orphan_evidence_reference_is_rejected(database):
    migrate(database)
    with pytest.raises(IntegrityError):
        with database.begin() as connection:
            connection.exec_driver_sql("INSERT INTO artifact_attempt_versions VALUES ('attempt', 'missing', 1)")


def test_reviewed_downgrade_and_reupgrade(database):
    migrate(database)
    with database.begin() as connection:
        command.downgrade(migration_config(connection), "0001_operational")
    migrate(database)
    with database.connect() as connection:
        require_current_schema(connection)


def test_postgres_job_repository_preserves_claim_and_completion_contract(database):
    migrate(database)
    repository = PostgresJobRepository(
        database.url.render_as_string(hide_password=False), engine=database
    )
    task = TaskContract(
        origin="postgres-test", skill="rigel.skill.code_generation", payload={"spec": "echo"},
        confidence_threshold=0.8,
    )
    job = repository.enqueue(task_id=task.task_id, task=task, idempotency_key="postgres-job")
    assert repository.get_task(job.job_id) == task
    claimed = repository.claim(worker_id="postgres-worker", lease_seconds=30)
    assert claimed is not None
    running, attempt = claimed
    assert running.status.value == "running"
    repository.heartbeat(job_id=job.job_id, lease_token=attempt.lease_token, lease_seconds=30)
    completed = repository.complete(
        job_id=job.job_id, lease_token=attempt.lease_token,
        output_ref="job-output", result={"status": "complete"},
    )
    assert completed.status.value == "completed"
    assert repository.get_result(job.job_id) == {"status": "complete"}
    assert repository.attempts(job.job_id)[0].outcome.value == "completed"
    assert [row["reason"] for row in repository.transitions(job.job_id)] == [
        "enqueue", "claim", "completed",
    ]
    repository.close()


def test_postgres_artifact_store_publishes_external_payload_and_enforces_scope(database, tmp_path):
    migrate(database)
    objects = LocalObjectStorage(str(tmp_path / "objects"))
    store = PostgresArtifactStore(database.url.render_as_string(hide_password=False), engine=database, object_storage=objects)
    store.record([{"filename": "a.txt", "content": "hello"}], "", "task", "skill", project_id="project")
    row = store.get_version("::a.txt", 1, project_id="project")
    assert row["content"] == "hello"
    assert row["object_id"] == "::a.txt/v1"
    with pytest.raises(PermissionError):
        store.get_version("::a.txt", 1, project_id="wrong")


def test_account_store_works_against_the_migrated_postgres_schema(database):
    from core.accounts.store import AccountError, AccountStore

    migrate(database)
    store = AccountStore(str(database.url), engine=database)
    assert store.has_users() is False
    store.create_user("a@x.io", "operator")
    with pytest.raises(AccountError, match="already exists"):
        store.create_user("A@x.io", "admin")
    token, record = store.create_token("a@x.io", role="viewer", ttl_days=1)
    principal = store.authenticate(token)
    assert (principal.id, principal.role, principal.organization_id) == ("user:a@x.io", "viewer", "default")
    store.revoke_token(record["id"])
    assert store.authenticate(token) is None
    store.deactivate_user("a@x.io")
    assert store.has_users() is True


def test_postgres_goals_and_jobs_are_scoped_by_organization(database):
    from core.contracts import GoalContract
    from core.goals.postgres_store import PostgresGoalStore

    migrate(database)
    url = database.url.render_as_string(hide_password=False)
    goals = PostgresGoalStore(url, engine=database)
    a = GoalContract(origin="t", objective="a", confidence_threshold=0.5, organization_id="org-a")
    b = GoalContract(origin="t", objective="b", confidence_threshold=0.5)
    goals.create_goal(a)
    goals.create_goal(b)
    assert goals.get_goal_for(a.goal_id, organization_id="org-a").organization_id == "org-a"
    assert goals.get_goal_for(a.goal_id, organization_id="default") is None
    assert [g.goal_id for g in goals.list_goals(organization_id="default")] == [b.goal_id]
    assert len(goals.list_goals(organization_id=None)) == 2

    jobs = PostgresJobRepository(url, engine=database)
    task = TaskContract(origin="t", skill="s.k", payload={}, confidence_threshold=0.5, organization_id="org-a")
    job = jobs.enqueue(task_id=task.task_id, task=task, idempotency_key="scoped")
    assert job.organization_id == "org-a"
    assert jobs.get_job_for(job.job_id, organization_id="org-a") == job
    assert jobs.get_job_for(job.job_id, organization_id="default") is None
    assert [j.job_id for j in jobs.list_jobs(organization_id="org-a")] == [job.job_id]
    assert jobs.list_jobs(organization_id="default") == []
    assert [j.job_id for j in jobs.list_jobs_all_organizations()] == [job.job_id]
    jobs.close()


def test_postgres_task_log_and_review_queue_are_scoped_by_organization(database):
    from agents.andromeda.state import AndromedaState
    from core.storage import PostgresReviewQueue, PostgresTaskLog

    migrate(database)
    url = database.url.render_as_string(hide_password=False)
    log, queue = PostgresTaskLog(url, engine=database), PostgresReviewQueue(url, engine=database)

    def state(task_id, org):
        return AndromedaState(task_id=task_id, origin="t", task_type="code", status="complete", payload={},
                              required_skills=["s.k"], priority="normal", issued_at="2026-11-07T10:00:00+00:00",
                              timeout_ms=1000, organization_id=org)

    log.write(state("t-a", "org-a"))
    log.write(state("t-b", "org-b"))
    assert log.get("t-a", organization_id="org-a")["organization_id"] == "org-a"
    assert log.get("t-a", organization_id="org-b") is None
    assert [r["task_id"] for r in log.recent(10, organization_id="org-a")] == ["t-a"]
    assert log.stats(organization_id="org-a")["total"] == 1 and log.stats(organization_id=None)["total"] == 2
    log.update_status("t-a", "code", "approved")
    assert log.stats(organization_id="org-a")["total"] == 2

    queue.enqueue("q-a", "code", 0.4, {}, organization_id="org-a")
    queue.enqueue("q-b", "code", 0.4, {})
    assert queue.get_for("q-a", organization_id="org-a")["task_id"] == "q-a"
    assert queue.get_for("q-a", organization_id="default") is None
    assert [i["task_id"] for i in queue.get_pending(organization_id="default")] == ["q-b"]
    assert queue.get_stats(organization_id="org-a")["pending"] == 1
    assert len(queue.get_pending(organization_id=None)) == 2


def test_postgres_artifacts_are_scoped_by_organization_and_legacy_rows_backfilled(database):
    migrate(database, "0008_review_task_scope")
    with database.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO artifact_versions (identity_key, version, content, content_hash, filename, task_id, skill, created_at) "
            "VALUES ('::old.py', 1, 'x', 'h', 'old.py', 't', 's', 'now')")
    migrate(database)
    store = PostgresArtifactStore(database.url.render_as_string(hide_password=False), engine=database)
    store.record([{"filename": "a.py", "content": "mine"}], "", "t", "s", organization_id="org-a")
    key = "org:org-a::::a.py"
    assert store.history(key, organization_id="org-a")[0]["version"] == 1
    assert store.history(key, organization_id="org-b") == []
    assert store.get_version(key, 1, organization_id="org-b") is None
    assert store.latest_version_number(key, organization_id="org-b") is None
    assert [f["filename"] for f in store.list_files(organization_id="org-a")] == ["a.py"]
    assert [f["filename"] for f in store.list_files(organization_id="default")] == ["old.py"]
    assert len(store.list_files(organization_id=None)) == 2
    with database.connect() as connection:
        assert connection.exec_driver_sql("SELECT organization_id FROM artifact_versions WHERE identity_key='::old.py'").scalar() == "default"
