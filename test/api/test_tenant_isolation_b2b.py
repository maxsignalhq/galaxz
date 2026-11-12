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
    }
    assert refused, "expected platform-wide routes to exist"
    for method, path in refused:
        response = client.request(method, _probe(path), json={}, headers=b)
        assert response.status_code == 403 and response.json() == {"error": "forbidden"}, (method, path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/audit/events"), ("GET", "/audit/verify"), ("GET", "/config"), ("POST", "/config"),
    ("POST", "/forge/agent"), ("GET", "/orion/export"), ("GET", "/finetune/candidates"), ("GET", "/lessons"),
    ("GET", "/scorecards"), ("GET", "/github/installations"),
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
