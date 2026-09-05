from __future__ import annotations

from fastapi.testclient import TestClient

import services.andromeda_service as service

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


class _Registry:
    def health_check(self) -> dict:
        return {"status": "ok"}

    def get_all_skills(self) -> list:
        return []

    def get_agents_for_skill(self, skill_id: str) -> list:
        return []

    def list_agents(self) -> list:
        return []


class _TaskLog:
    def stats(self) -> dict:
        return {"total": 0}


class _Andromeda:
    registry = _Registry()
    task_log = _TaskLog()


class _Aether:
    class Redis:
        def ping(self) -> bool:
            return True

    redis = Redis()

    def close(self) -> None:
        pass


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    monkeypatch.setenv("JOB_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service, "boot", lambda: _Andromeda())
    monkeypatch.setattr(service, "get_aether_client", lambda: _Aether())
    monkeypatch.setattr(service, "_job_repository", None)
    service.app.middleware_stack = None
    return TestClient(service.app)


def test_submit_inspect_and_cancel_durable_job(monkeypatch, tmp_path) -> None:
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/jobs",
            headers=AUTH_HEADERS,
            json={
                "task": "Generate a validator",
                "skill_id": "code_generation",
                "idempotency_key": "request-1",
                "priority": 5,
            },
        )
        assert response.status_code == 202
        created = response.json()
        assert created["status"] == "queued"
        job_id = created["job_id"]

        duplicate = client.post(
            "/jobs",
            headers=AUTH_HEADERS,
            json={
                "task": "Generate a validator",
                "skill_id": "code_generation",
                "idempotency_key": "request-1",
                "priority": 5,
            },
        )
        assert duplicate.json()["job_id"] == job_id

        detail = client.get(f"/jobs/{job_id}", headers=AUTH_HEADERS)
        assert detail.status_code == 200
        assert detail.json()["transitions"][0]["reason"] == "enqueue"
        listed = client.get("/jobs?limit=10", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        assert [item["job_id"] for item in listed.json()] == [job_id]

        cancelled = client.post(f"/jobs/{job_id}/cancel", headers=AUTH_HEADERS)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        repeated = client.post(f"/jobs/{job_id}/cancel", headers=AUTH_HEADERS)
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "cancelled"


def test_job_endpoints_require_authentication(monkeypatch, tmp_path) -> None:
    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/jobs",
            json={
                "task": "Generate a validator",
                "skill_id": "code_generation",
                "idempotency_key": "request-unauthorized",
            },
        )
    assert response.status_code == 401
