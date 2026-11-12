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
