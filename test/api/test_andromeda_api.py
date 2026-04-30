from fastapi.testclient import TestClient

import services.andromeda_service as andromeda_service

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _reset_auth(monkeypatch) -> None:
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    andromeda_service.app.middleware_stack = None


class FakeRegistry:
    def __init__(self) -> None:
        self._skills = {
            "rigel.skill.code_generation": ["rigel"],
            "requirements_to_test_cases": ["vega"],
        }

    def health_check(self) -> dict:
        return {"status": "ok", "skill_count": 6, "agents": ["rigel"]}

    def get_all_skills(self) -> list:
        return [object()] * 6

    def get_agents_for_skill(self, skill_id: str) -> list:
        return self._skills.get(skill_id, [])


class FakeAndromeda:
    def __init__(self, fail: bool = False) -> None:
        self.registry = FakeRegistry()
        self.fail = fail
        self.route_calls: list[dict] = []

    def route(self, **kwargs) -> dict:
        task_payload = kwargs.get("task")
        if "task" in kwargs:
            task = kwargs["task"]
            kwargs = {
                **kwargs,
                "task": {
                    "origin": task.origin,
                    "skill": task.skill,
                    "payload": task.payload,
                    "confidence_threshold": task.confidence_threshold,
                    "deadline_ms": task.deadline_ms,
                },
            }
        self.route_calls.append(kwargs)
        if self.fail:
            raise RuntimeError("route failed")
        return {
            "task_id": "task-123",
            "task_type": task_payload.skill.split(".")[-1] if task_payload is not None else kwargs["task_type"],
            "required_skills": [task_payload.skill] if task_payload is not None else kwargs["required_skills"],
            "assigned_agent": "rigel",
            "status": "complete",
            "confidence": 0.91,
            "payload": task_payload.payload if task_payload is not None else kwargs["payload"],
            "result": {"code": "print('ok')"},
        }


def test_health_endpoint_reports_registry_status(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "andromeda", "version": "0.1.0"}


def test_task_endpoint_normalizes_rigel_skill_and_routes_payload(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "Generate an input validator", "skill_id": "code_generation"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["assigned_agent"] == "rigel"
    assert body["required_skills"] == ["rigel.skill.code_generation"]

    assert fake.route_calls == [
        {
            "task": {
                "origin": "andromeda_api",
                "skill": "rigel.skill.code_generation",
                "payload": {
                    "spec": "Generate an input validator",
                    "task": "Generate an input validator",
                },
                "confidence_threshold": 0.65,
                "deadline_ms": None,
            },
        }
    ]


def test_task_endpoint_maps_pr_review_payload(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "diff --git a/app.py b/app.py\n+print('token')", "skill_id": "pr_review"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    payload = fake.route_calls[0]["task"]["payload"]
    assert payload["diff"] == "diff --git a/app.py b/app.py\n+print('token')"
    assert payload["spec"] == payload["diff"]
    assert payload["task"] == payload["diff"]


def test_task_endpoint_returns_500_when_router_fails(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda(fail=True)
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "Generate an input validator", "skill_id": "rigel.skill.code_generation"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "route failed"
