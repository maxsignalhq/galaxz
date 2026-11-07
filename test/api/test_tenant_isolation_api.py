"""Organization isolation of goals and jobs (accounts phase B1)."""

import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from core.accounts import get_account_store
from test.api.test_goals_api import FakeAether, _build_andromeda


def _headers(email, organization):
    store = get_account_store()
    store.create_user(email, "admin", organization_id=organization)
    return {"Authorization": "Bearer " + store.create_token(email)[0]}


@pytest.fixture
def tenants(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
    monkeypatch.setenv("JOB_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(svc, "_job_repository", None)
    monkeypatch.setattr(svc, "_read_workspace_path", lambda: "")
    svc.app.middleware_stack = None
    andromeda = _build_andromeda(tmp_path)
    monkeypatch.setattr(svc, "boot", lambda: andromeda)
    monkeypatch.setattr(svc, "get_aether_client", lambda: FakeAether())
    a, b = _headers("a@x.io", "org-a"), _headers("b@x.io", "org-b")
    with TestClient(svc.app, raise_server_exceptions=False) as client:
        client._andromeda = andromeda
        yield client, a, b


def _goal(client, headers):
    response = client.post("/goals", json={"objective": "ship it", "confidence_threshold": 0.65}, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["goal"]["goal_id"]


def _job(client, headers, key="k1"):
    response = client.post(
        "/jobs", json={"task": "write a validator", "skill_id": "code_generation", "idempotency_key": key}, headers=headers
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_goal_is_stamped_with_the_callers_organization(tenants):
    client, a, _ = tenants
    goal_id = _goal(client, a)
    stored = client._andromeda.goal_store.get_goal(UUID(goal_id))
    assert stored.organization_id == "org-a"


def test_other_organization_gets_404_on_every_goal_route(tenants):
    client, a, b = tenants
    goal_id = _goal(client, a)
    task_id = client.get(f"/goals/{goal_id}", headers=a).json()["projects"][0]["tasks"][0]["task_id"]
    assert client.get(f"/goals/{goal_id}", headers=a).status_code == 200
    for method, path in (
        ("get", f"/goals/{goal_id}"),
        ("post", f"/goals/{goal_id}/resume"),
        ("post", f"/goals/{goal_id}/pause"),
        ("post", f"/goals/{goal_id}/cancel"),
        ("post", f"/goals/{goal_id}/tasks/{task_id}/rerun"),
    ):
        response = getattr(client, method)(path, headers=b)
        assert response.status_code == 404, (method, path, response.status_code)
        # indistinguishable from a goal that never existed
        missing = getattr(client, method)(path.replace(goal_id, str(uuid4())), headers=b)
        assert (response.status_code, response.json()) == (missing.status_code, missing.json())


def test_goal_listing_is_per_organization(tenants):
    client, a, b = tenants
    goal_id = _goal(client, a)
    assert [g["goal_id"] for g in client.get("/goals", headers=a).json()] == [goal_id]
    assert client.get("/goals", headers=b).json() == []


def test_other_organization_cannot_read_or_cancel_a_job(tenants):
    client, a, b = tenants
    job_id = _job(client, a)
    assert client.get(f"/jobs/{job_id}", headers=a).status_code == 200
    assert client.get(f"/jobs/{job_id}", headers=b).status_code == 404
    assert client.post(f"/jobs/{job_id}/cancel", headers=b).status_code == 404
    assert client.get(f"/jobs/{job_id}", headers=a).json()["job"]["status"] != "cancelled"
    assert [j["job_id"] for j in client.get("/jobs", headers=a).json()] == [job_id]
    assert client.get("/jobs", headers=b).json() == []


def test_idempotency_keys_do_not_collide_across_organizations(tenants):
    client, a, b = tenants
    first, second = _job(client, a, "same"), _job(client, b, "same")
    assert first != second
    assert _job(client, a, "same") == first


def test_job_task_carries_the_organization_to_the_worker(tenants):
    client, a, _ = tenants
    job_id = _job(client, a)
    job = svc._jobs().get_job(UUID(job_id))
    assert job.organization_id == "org-a"
    assert svc._jobs().get_task(job.job_id).organization_id == "org-a"


def test_closed_reads_require_credentials(tenants):
    client, a, _ = tenants
    for path in ("/status", "/agents", "/tasks/recent", "/tasks/stats", "/review/queue"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=a).status_code in (200, 500), path


def test_service_never_uses_an_unscoped_goal_or_job_lookup():
    source = Path(svc.__file__).read_text()
    # the one remaining unscoped goal_store.get_goal is the review-resume path, which moves in B2
    assert source.count("goal_store.get_goal(") == 1
    assert "organization_id=None" not in source
    assert "_all_organizations" not in source
    # the single remaining get_job is cancel_job re-reading a job it already authorised
    assert len(re.findall(r"\.get_job\(", source)) == 1
