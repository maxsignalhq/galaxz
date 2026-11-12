"""Organization isolation of artifacts, memory, repositories, policy grants and GitHub (accounts phase B2b)."""

from uuid import UUID

import pytest

import services.andromeda_service as svc
from core.artifacts.store import ArtifactStore, identity_key
from core.nebula.store import NebulaStore
from core.policy.grants import GrantStore
from core.repositories import RepositoryStore
from test.api.test_tenant_isolation_api import tenants  # noqa: F401  (fixture)


@pytest.fixture
def repos(monkeypatch, tmp_path):
    store = RepositoryStore(str(tmp_path / "repos.db"))
    monkeypatch.setattr(svc, "_repository_store", store)
    return store


# --- artifacts ----------------------------------------------------------------------------------

def test_same_path_in_two_organizations_keeps_separate_histories(tmp_path):
    store = ArtifactStore(str(tmp_path / "a.db"))
    file = [{"filename": "app.py", "content": "one"}]
    store.record(file, workspace_root="/w", task_id="t1", skill="s", organization_id="org-a")
    store.record([{"filename": "app.py", "content": "other"}], workspace_root="/w", task_id="t2", skill="s", organization_id="org-b")
    key_a, key_b = identity_key("/w", "app.py", "org-a"), identity_key("/w", "app.py", "org-b")
    assert key_a != key_b
    assert [h["version"] for h in store.history(key_a, organization_id="org-a")] == [1]
    assert [h["version"] for h in store.history(key_b, organization_id="org-b")] == [1]
    assert store.history(key_a, organization_id="org-b") == []  # even with the right key
    assert store.get_version(key_a, 1, organization_id="org-b") is None
    assert [f["identity_key"] for f in store.list_files(organization_id="org-a")] == [key_a]
    assert store.list_files(organization_id="org-c") == []


def test_default_organization_keys_are_unchanged():
    assert identity_key("/w", "a.py") == "/w::a.py"


def test_rows_without_an_organization_are_backfilled_to_default(tmp_path):
    path = str(tmp_path / "old.db")
    store = ArtifactStore(path)
    store.record([{"filename": "a.py", "content": "x"}], workspace_root="", task_id="t", skill="s")
    store._conn.execute("UPDATE artifact_versions SET organization_id = NULL")
    store._conn.commit()
    reopened = ArtifactStore(path)
    assert [f["filename"] for f in reopened.list_files(organization_id="default")] == ["a.py"]


def test_artifact_routes_ignore_a_claimed_organization(tenants):  # noqa: F811
    client, a, b = tenants
    client._andromeda.artifact_store.record(
        [{"filename": "secret.py", "content": "x"}], workspace_root="", task_id="t", skill="s", organization_id="org-a"
    )
    assert [f["filename"] for f in client.get("/artifacts", headers=a).json()] == ["secret.py"]
    assert client.get("/artifacts", headers=b).json() == []
    assert client.get("/artifacts/history?path=secret.py", headers=a).status_code == 200
    for headers in (b,):
        assert client.get("/artifacts/history?path=secret.py&organization_id=org-a", headers=headers).status_code == 404
        assert client.get("/artifacts/diff?path=secret.py&organization_id=org-a", headers=headers).status_code == 404
        rollback = client.post(
            "/artifacts/rollback", json={"path": "secret.py", "version": 1, "organization_id": "org-a"}, headers=headers
        )
        assert rollback.status_code == 404


# --- memory ---------------------------------------------------------------------------------------

def test_memory_is_per_organization(tenants):  # noqa: F811
    client, a, b = tenants
    created = client.post("/memory", json={"namespace": "global", "content": "launch codename falcon"}, headers=a)
    assert created.status_code == 201
    memory_id = created.json()["memory_id"]
    assert len(client.get("/memory?namespace=global&q=falcon", headers=a).json()) == 1
    assert client.get("/memory?namespace=global&q=falcon", headers=b).json() == []
    assert client.get("/memory/namespaces", headers=b).json() == []
    assert client.delete(f"/memory/{memory_id}", headers=b).status_code == 404
    assert client.delete(f"/memory/{memory_id}", headers=a).status_code == 200


def test_nebula_recall_never_crosses_organizations(tmp_path):
    store = NebulaStore(str(tmp_path / "n.db"))
    store.remember("global", "falcon plan", organization_id="org-a")
    assert store.recall(["global"], query="falcon", organization_id="org-b") == []
    assert store.list("global", organization_id="org-b") == []
    assert len(store.recall(["global"], query="falcon", organization_id="org-a")) == 1


# --- policy grants --------------------------------------------------------------------------------

def test_a_grant_is_only_usable_in_its_own_organization(tmp_path):
    grants = GrantStore(str(tmp_path / "p.db"))
    grants.issue(origin="o", skill="s", digest="d", organization_id="org-a")
    assert grants.consume(origin="o", skill="s", digest="d", organization_id="default") is False
    assert grants.consume(origin="o", skill="s", digest="d", organization_id="org-b") is False
    assert grants.consume(origin="o", skill="s", digest="d", organization_id="org-a") is True
    assert grants.consume(origin="o", skill="s", digest="d", organization_id="org-a") is False  # single use


# --- repositories & GitHub ------------------------------------------------------------------------

REPO = {"provider": "github", "owner": "acme", "name": "api", "installation_scope": "inst-1"}


def test_repository_is_visible_only_to_the_registering_organization(tenants, repos):  # noqa: F811
    client, a, b = tenants
    created = client.post("/repositories", json=REPO, headers=a)
    assert created.status_code == 201 and created.json()["organization_id"] == "org-a"
    repository_id = created.json()["repository_id"]
    assert client.get(f"/repositories/{repository_id}", headers=a).status_code == 200
    assert client.get(f"/repositories/{repository_id}", headers=b).status_code == 404


def test_a_repository_cannot_be_registered_by_two_organizations(tenants, repos):  # noqa: F811
    client, a, b = tenants
    assert client.post("/repositories", json=REPO, headers=a).status_code == 201
    assert client.post("/repositories", json={**REPO, "installation_scope": "inst-2"}, headers=b).status_code == 422
    assert client.post("/repositories", json=REPO, headers=a).status_code == 201  # re-registering your own is fine


def test_a_goal_cannot_bind_another_organizations_repository(tenants, repos):  # noqa: F811
    client, a, b = tenants
    repository_id = client.post("/repositories", json=REPO, headers=a).json()["repository_id"]
    response = client.post(
        "/goals", json={"objective": "ship it", "confidence_threshold": 0.65, "repository_id": repository_id}, headers=b
    )
    assert response.status_code == 422


def test_github_actions_need_a_repository_registered_to_the_caller(tenants, repos, monkeypatch):  # noqa: F811
    client, a, b = tenants
    calls = []

    class Client:
        def create_check_run(self, owner, repository, **kwargs):
            calls.append((owner, repository))
            return {"ok": True}

    monkeypatch.setattr(svc, "_github_client", lambda installation_id: Client())
    body = {"installation_id": 1, "owner": "acme", "repository": "api", "head_sha": "a" * 40, "name": "n", "passed": True, "summary": "s"}
    assert client.post("/github/check-run", json=body, headers=b).status_code == 404  # not registered at all
    client.post("/repositories", json=REPO, headers=a)
    assert client.post("/github/check-run", json=body, headers=b).status_code == 404  # someone else's
    assert client.post("/github/check-run", json=body, headers=a).status_code == 200
    assert calls == [("acme", "api")]


def test_installation_listings_are_default_organization_only(tenants, monkeypatch):  # noqa: F811
    client, a, _ = tenants
    assert client.get("/github/installations", headers=a).status_code == 403
    assert client.get("/github/installations/1/repositories", headers=a).status_code == 403


def test_pre_tenancy_repository_table_is_rebuilt_with_existing_rows_in_default(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE repositories (
        repository_id TEXT PRIMARY KEY, provider TEXT NOT NULL, owner TEXT NOT NULL,
        name TEXT NOT NULL, installation_scope TEXT NOT NULL, local_path TEXT,
        active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
        UNIQUE(provider, owner, name, installation_scope))""")
    conn.execute("INSERT INTO repositories VALUES ('r1','github','acme','api','i',NULL,1,'2026-01-01')")
    conn.commit()
    conn.close()
    store = RepositoryStore(path)
    assert store.get("r1", organization_id="default").organization_id == "default"
    assert store.holder("github", "acme", "api") == "default"


# --- platform-wide routes are closed to other organizations --------------------------------------

def _probe(path):
    return path.replace("{", "").replace("}", "")


def test_every_route_is_either_declared_tenant_scoped_or_refused_to_other_organizations(tenants):  # noqa: F811
    from agents.andromeda.middleware.auth import _EXEMPT_ROUTES
    from core.accounts import tenant_scoped

    client, _, b = tenants
    exempt = set(_EXEMPT_ROUTES)
    scoped, refused = set(), []
    for route in svc.app.routes:
        for method in getattr(route, "methods", None) or ():
            if method in ("HEAD", "OPTIONS") or (method, route.path) in exempt:
                continue
            if tenant_scoped(method, _probe(route.path)):
                scoped.add((method, route.path))
            else:
                refused.append((method, route.path))
    # Adding a route to this list is the review step: it must filter by the principal's organization.
    assert scoped == {
        ("GET", "/auth/me"), ("POST", "/task"), ("POST", "/jobs"), ("GET", "/jobs"), ("GET", "/jobs/{job_id}"),
        ("POST", "/jobs/{job_id}/cancel"), ("POST", "/goals"), ("GET", "/goals"), ("GET", "/goals/{goal_id}"),
        ("POST", "/goals/{goal_id}/resume"), ("POST", "/goals/{goal_id}/pause"), ("POST", "/goals/{goal_id}/cancel"),
        ("POST", "/goals/{goal_id}/tasks/{task_id}/rerun"), ("GET", "/review/queue"), ("GET", "/review/queue/stats"),
        ("GET", "/review/queue/{task_id}"), ("POST", "/review/queue/{task_id}/approve"),
        ("POST", "/review/queue/{task_id}/accept"), ("POST", "/review/queue/{task_id}/reject"),
        ("POST", "/tasks/{task_id}/feedback"), ("GET", "/tasks/recent"), ("GET", "/tasks/stats"),
        ("GET", "/tasks/throughput"), ("GET", "/status"), ("POST", "/memory"), ("GET", "/memory"),
        ("GET", "/memory/namespaces"), ("DELETE", "/memory/{memory_id}"), ("GET", "/artifacts"),
        ("GET", "/artifacts/history"), ("GET", "/artifacts/diff"), ("POST", "/artifacts/rollback"),
        ("POST", "/repositories"), ("GET", "/repositories/{repository_id}"), ("POST", "/github/pull-request"),
        ("POST", "/github/check-run"), ("GET", "/agents"), ("GET", "/catalog"), ("GET", "/quasar"),
        ("GET", "/wormhole"), ("GET", "/openapi.json"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
        ("GET", "/orion/analytics"), ("GET", "/orion/export"), ("GET", "/scorecards/key"), ("GET", "/scorecards"),
        ("GET", "/scorecards/{skill_id}"), ("POST", "/lessons/propose"), ("GET", "/lessons"),
        ("POST", "/lessons/{candidate_id}/approve"), ("POST", "/lessons/{candidate_id}/reject"),
    }
    assert refused, "expected platform-wide routes to exist"
    for method, path in refused:
        response = client.request(method, _probe(path), json={}, headers=b)
        assert response.status_code == 403 and response.json() == {"error": "forbidden"}, (method, path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/audit/events"), ("GET", "/audit/verify"), ("GET", "/config"), ("POST", "/config"),
    ("POST", "/forge/agent"), ("GET", "/finetune/candidates"), ("POST", "/orion/training/run"),
    ("GET", "/github/installations"),
])
def test_other_organizations_admin_cannot_reach_platform_wide_routes(tenants, method, path):  # noqa: F811
    client, a, _ = tenants
    assert client.request(method, path, json={}, headers=a).status_code == 403


# --- review follow-ups -----------------------------------------------------------------------------

def test_repository_ownership_ignores_case(tenants, repos):  # noqa: F811
    client, a, b = tenants
    assert client.post("/repositories", json=REPO, headers=a).status_code == 201
    mixed = {**REPO, "owner": "Acme", "name": "API"}
    assert client.post("/repositories", json=mixed, headers=b).status_code == 422
    assert repos.holder("GitHub", "ACME", "Api") == "org-a"


def test_artifacts_with_namespaced_keys_work_with_object_storage(tmp_path):
    from core.artifacts.object_storage import LocalObjectStorage

    store = ArtifactStore(str(tmp_path / "o.db"), object_storage=LocalObjectStorage(str(tmp_path / "objects")))
    store.record([{"filename": "a.txt", "content": "hello"}], "", "t", "s", organization_id="org-a")
    key = identity_key("", "a.txt", "org-a")
    assert store.get_version(key, 1, organization_id="org-a")["content"] == "hello"
    assert store.get_version(key, 1, organization_id="org-b") is None
    assert store.get_version(key, 1)["content"] == "hello"  # platform internals (the completion publisher)


# --- Orion (accounts phase B3) ---------------------------------------------------------------------

def _orion_db(tmp_path, rows):
    import asyncio
    import sqlite3

    from orion.storage.event_log import EventLog

    path = str(tmp_path / "orion-events.db")
    asyncio.run(EventLog().init_db(path))
    with sqlite3.connect(path) as conn:
        for i, (org, extra) in enumerate(rows):
            conn.execute(
                "INSERT INTO events (id, task_id, skill_id, agent_id, domain, outcome, confidence, human_verified, "
                "human_correction, latency_ms, created_at, quarantined, organization_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),0,?)",
                (f"e{i}", f"t{i}", "rigel.skill.code_generation", "rigel", "code", "success", 0.95, 1, extra, 10, org),
            )
    return path


def test_orion_analytics_and_export_only_cover_the_callers_organization(tenants, tmp_path, monkeypatch):  # noqa: F811
    client, a, b = tenants
    path = _orion_db(tmp_path, [("org-a", None), ("org-a", None), ("org-b", None)])
    monkeypatch.setattr(svc, "_orion_db_path", lambda: path)
    assert sum(client.get("/orion/analytics", headers=a).json()["outcome_counts"].values()) == 2
    assert sum(client.get("/orion/analytics", headers=b).json()["outcome_counts"].values()) == 1
    exported_a = [line for line in client.get("/orion/export", headers=a).text.splitlines() if line]
    assert len(exported_a) == 2 and all('"org-a"' in line for line in exported_a)


def test_scorecards_are_computed_from_the_callers_events_only(tmp_path):
    from core.scorecards.metrics import build_scorecards

    path = _orion_db(tmp_path, [("org-a", None)] * 3 + [("org-b", None)])
    assert build_scorecards(path, organization_id="org-a")[0]["metrics"]["tasks"] == 3
    assert build_scorecards(path, organization_id="org-b")[0]["metrics"]["tasks"] == 1
    assert build_scorecards(path, organization_id="org-c") == []


def test_tenant_events_never_reach_platform_wide_curation_or_training(tmp_path):
    import asyncio

    from core.contracts import FeedbackEvent, OutcomeType
    from orion.storage.event_log import EventLog

    path = _orion_db(tmp_path, [("org-a", None), ("default", None)])
    log = EventLog()
    asyncio.run(log.init_db(path))
    assert [e["id"] for e in asyncio.run(log.get_uncurated_events())] == ["e1"]
    assert [e["id"] for e in asyncio.run(log.get_unexported_events())] == ["e1"]
    assert asyncio.run(log.count_unexported_by_domain()) == {"code": 1}
    for org in ("org-a", "default"):
        asyncio.run(log.append(FeedbackEvent(
            task_category="code", agent_id="h", outcome=OutcomeType.approved, confidence_score=0.9,
            input_hash="x", agent_output={"secret": org}, latency_ms=0, organization_id=org)))
    assert [e.agent_output for e in asyncio.run(log.get_window("code", 24))] == [{"secret": "default"}]
    assert asyncio.run(log.list_domains()) == ["code"]
    assert [e.agent_output for e in asyncio.run(log.get_by_agent("h"))] == [{"secret": "default"}]


def test_lessons_are_proposed_listed_and_decided_per_organization(tenants, tmp_path, monkeypatch):  # noqa: F811
    from orion.core.lesson_store import LessonStore
    from orion.pipeline.lesson_proposal import propose_lessons

    client, a, b = tenants
    db = _orion_db(tmp_path, [("org-a", f"use fromisoformat ({i})") for i in range(3)] + [("org-b", "other")])
    store = LessonStore(str(tmp_path / "lessons.db"))
    monkeypatch.setattr(svc, "_lesson_store", lambda: store)
    created = propose_lessons(db, store, lambda system, user: '["Prefer fromisoformat."]', min_examples=3, organization_id="org-a")
    assert [c.organization_id for c in created] == ["org-a"]
    assert propose_lessons(db, store, lambda s, u: '["x"]', min_examples=3, organization_id="org-b") == []  # one event only
    candidate_id = created[0].candidate_id
    assert len(client.get("/lessons", headers=a).json()["lessons"]) == 1
    assert client.get("/lessons", headers=b).json()["lessons"] == []
    body = {"reviewed_by": "x"}
    assert client.post(f"/lessons/{candidate_id}/approve", json=body, headers=b).status_code == 404
    assert client.post(f"/lessons/{candidate_id}/reject", json=body, headers=b).status_code == 404
    approved = client.post(f"/lessons/{candidate_id}/approve", json=body, headers=a)
    assert approved.status_code == 200
    # the lesson lands in the approving organization's memory only
    nebula = client._andromeda.nebula
    assert len(nebula.list("skill:rigel.skill.code_generation", organization_id="org-a")) == 1
    assert nebula.list("skill:rigel.skill.code_generation", organization_id="org-b") == []


def test_feedback_emitted_by_rigel_carries_the_tasks_organization(monkeypatch):
    import agents.rigel.agent as rigel

    sent = []

    class Aether:
        def publish_event(self, stream, payload):
            sent.append(payload)

        def close(self):
            pass

    monkeypatch.setattr(rigel, "get_aether_client", lambda: Aether())
    agent = rigel.RigelAgent.__new__(rigel.RigelAgent)
    agent._emit_feedback(None, "rigel.skill.code_generation", 0.9, None, 5, "success", organization_id="org-a")
    assert sent[0]["organization_id"] == "org-a"


def test_review_decisions_publish_feedback_in_the_items_organization(tenants, monkeypatch):  # noqa: F811
    client, a, _ = tenants
    published = []
    fake = type("A", (), {"publish_event": lambda self, stream, payload: published.append(payload), "close": lambda self: None})()
    monkeypatch.setattr(svc, "_aether", fake)
    client._andromeda.review_queue.enqueue("rq-1", "code", 0.4, {"spec": "x"}, organization_id="org-a")
    assert client.post("/review/queue/rq-1/approve", headers=a).status_code == 200
    assert published and published[-1]["organization_id"] == "org-a"


def test_a_pre_b3_events_database_is_upgraded_by_the_api_readers(tenants, tmp_path, monkeypatch):  # noqa: F811
    import sqlite3

    client, a, _ = tenants
    path = str(tmp_path / "old-events.db")
    with sqlite3.connect(path) as conn:  # an events table exactly as it was before B3
        conn.execute("""CREATE TABLE events (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, skill_id TEXT NOT NULL, agent_id TEXT NOT NULL,
            domain TEXT NOT NULL, outcome TEXT NOT NULL, confidence REAL NOT NULL, human_verified INTEGER DEFAULT 0,
            payload TEXT, result TEXT, human_correction TEXT, latency_ms INTEGER,
            created_at TEXT DEFAULT (datetime('now')), quarantined INTEGER DEFAULT 0, exported_at TEXT)""")
        conn.execute("INSERT INTO events (id, task_id, skill_id, agent_id, domain, outcome, confidence) "
                     "VALUES ('old','t','rigel.skill.code_generation','rigel','code','success',0.9)")
    monkeypatch.setattr(svc, "_orion_schema_checked", set())
    client._andromeda.orion = type("O", (), {"_cfg": type("C", (), {"db_path": path})()})()
    default = _headers_for("old@x.io", "default")
    assert sum(client.get("/orion/analytics", headers=default).json()["outcome_counts"].values()) == 1
    assert len([x for x in client.get("/orion/export", headers=default).text.splitlines() if x]) == 1
    assert client.get("/orion/analytics", headers=a).json()["outcome_counts"] == {}


def _headers_for(email, organization):
    from core.accounts import get_account_store

    store = get_account_store()
    store.create_user(email, "admin", organization_id=organization)
    return {"Authorization": "Bearer " + store.create_token(email)[0]}


def test_scorecards_name_other_organizations_but_not_the_platform(tmp_path):
    from core.scorecards.metrics import build_scorecards

    path = _orion_db(tmp_path, [("org-a", None), ("default", None)])
    assert build_scorecards(path, organization_id="org-a")[0]["subject"]["organization_id"] == "org-a"
    assert "organization_id" not in build_scorecards(path, organization_id="default")[0]["subject"]
    assert "organization_id" not in build_scorecards(path, organization_id=None)[0]["subject"]


def test_finetune_detection_and_heuristics_ignore_tenant_events(tmp_path):
    import asyncio
    import sqlite3
    from datetime import datetime, timezone

    from orion.core.finetune_detector import FinetuneDetector
    from orion.pipeline.heuristic_generator import HeuristicGenerator

    path = _orion_db(tmp_path, [("org-a", None)] * 4 + [("default", None)])
    detector = FinetuneDetector(events_db_path=path, candidate_store=None, redis_url="redis://unused")
    assert asyncio.run(detector._query_agent_stats())[0][1] == 1  # only the default event is counted

    with sqlite3.connect(path) as conn:
        for org in ("org-a", "default"):
            conn.execute(
                "INSERT INTO feedback_events (id, task_id, task_category, agent_id, outcome, confidence_score, input_hash, "
                "agent_output, latency_ms, timestamp, organization_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"f-{org}", f"t-{org}", "code", "rigel", "completed", 0.9, "h", "{}", 1,
                 datetime.now(timezone.utc).isoformat(), org))
    weights = tmp_path / "weights.yaml"
    weights.write_text("weights: {}\n")
    generator = HeuristicGenerator(path, str(weights))
    assert len(generator._query_events("code", window_hours=24)) == 1
