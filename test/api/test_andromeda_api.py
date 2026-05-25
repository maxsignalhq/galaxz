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
            "vega.skill.requirements_to_test_cases": ["vega"],
            "vega.skill.test_case_execution": ["vega"],
        }

    def health_check(self) -> dict:
        return {"status": "ok", "skill_count": 6, "agents": ["rigel"]}

    def get_all_skills(self) -> list:
        return [object()] * 6

    def get_agents_for_skill(self, skill_id: str) -> list:
        return self._skills.get(skill_id, [])

    def list_agents(self) -> list:
        return ["rigel"]


class FakeTaskLog:
    def stats(self) -> dict:
        return {"total": 0}


class FakeAether:
    class Redis:
        def ping(self) -> bool:
            return True

    redis = Redis()

    def close(self) -> None:
        return None


class FakeAndromeda:
    def __init__(self, fail: bool = False) -> None:
        self.registry = FakeRegistry()
        self.task_log = FakeTaskLog()
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


class SequencedAndromeda(FakeAndromeda):
    def route(self, **kwargs) -> dict:
        super().route(**kwargs)
        task = kwargs["task"]
        if task.skill == "rigel.skill.code_generation":
            return {
                "task_id": "rigel-task",
                "task_type": "code_generation",
                "required_skills": ["rigel.skill.code_generation"],
                "assigned_agent": "rigel",
                "status": "complete",
                "confidence": 0.91,
                "issued_at": "2026-05-09T00:00:00Z",
                "completed_at": "2026-05-09T00:00:01Z",
                "result": {"code": "def convert(value):\n    return value", "language": "python"},
            }
        if task.skill == "vega.skill.requirements_to_test_cases":
            return {
                "task_id": "vega-task",
                "task_type": "requirements_to_test_cases",
                "required_skills": ["vega.skill.requirements_to_test_cases"],
                "assigned_agent": "vega",
                "status": "complete",
                "confidence": 0.88,
                "issued_at": "2026-05-09T00:00:01Z",
                "completed_at": "2026-05-09T00:00:02Z",
                "result": {"test_cases": [{"id": "TC-001"}], "total_count": 1},
            }
        raise AssertionError(task.skill)


def test_health_endpoint_reports_registry_status(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "get_aether_client", lambda: FakeAether())

    with TestClient(andromeda_service.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "andromeda"
    assert body["version"] == "1.0.0"
    assert body["checks"]["pulsar"] == {"status": "ok", "agent_count": 1}
    assert body["checks"]["aether"]["status"] == "ok"
    assert body["checks"]["task_log"] == {"status": "ok", "recent_tasks": 0}


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


def test_task_endpoint_keeps_vega_skill_and_routes_payload(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={
                "task": "Executed checkout regression: payment validation failed for expired cards.",
                "skill_id": "test_case_execution",
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    call = fake.route_calls[0]["task"]
    assert call["skill"] == "vega.skill.test_case_execution"
    assert call["payload"]["test_results"] == [
        {
            "tc_id": "UI-001",
            "status": "fail",
            "actual_result": "Executed checkout regression: payment validation failed for expired cards.",
        }
    ]


def test_task_endpoint_auto_routes_code_then_qa(monkeypatch):
    _reset_auth(monkeypatch)
    fake = SequencedAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    prompt = (
        "Write a Python script that converts measurements like Celsius to Fahrenheit. "
        "Then using same requirements create test cases in ISTQB style."
    )
    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": prompt, "skill_id": "auto", "route_mode": "auto"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["assigned_agent"] == "rigel+vega"
    assert body["required_skills"] == ["rigel.skill.code_generation", "vega.skill.requirements_to_test_cases"]
    assert body["result"]["steps"][0]["agent"] == "rigel"
    assert body["result"]["steps"][1]["agent"] == "vega"
    assert [call["task"]["skill"] for call in fake.route_calls] == [
        "rigel.skill.code_generation",
        "vega.skill.requirements_to_test_cases",
    ]
    first_payload = fake.route_calls[0]["task"]["payload"]
    assert "Do not create test cases" in first_payload["spec"]
    assert "ISTQB style" not in first_payload["spec"]
    assert "Generated implementation from Rigel" in fake.route_calls[1]["task"]["payload"]["raw_requirements"]


def test_task_endpoint_includes_task_ui_session_context_for_followups(monkeypatch):
    _reset_auth(monkeypatch)
    fake = FakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={
                "task": "Redo it and come back with the same program at 90% confidence.",
                "skill_id": "code_generation",
                "route_mode": "auto",
                "session_context": [
                    {
                        "role": "user",
                        "skill_id": "rigel.skill.code_generation",
                        "content": "Write a Python script that converts Celsius to Fahrenheit.",
                        "status": "complete",
                    },
                    {
                        "role": "agent",
                        "skill_id": "rigel.skill.code_generation",
                        "assigned_agent": "rigel",
                        "status": "complete",
                        "confidence": 0.6,
                        "content": "Code:\ndef c_to_f(c):\n    return c * 9 / 5 + 32",
                    },
                ],
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    call = fake.route_calls[0]
    payload = call["task"]["payload"]
    assert "Current user message:" in payload["spec"]
    assert "Redo it and come back with the same program at 90% confidence." in payload["spec"]
    assert "Write a Python script that converts Celsius to Fahrenheit." in payload["spec"]
    assert "def c_to_f" in payload["spec"]
    assert call["context"]["current_user_message"] == "Redo it and come back with the same program at 90% confidence."
    assert call["context"]["task_ui_session"][1]["confidence"] == 0.6


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


# --- Workspace execution tests ---


class WorkspaceAwareFakeAndromeda(FakeAndromeda):
    def route(self, **kwargs) -> dict:
        result = super().route(**kwargs)
        result["execution_result"] = {
            "executed_from": "workspace",
            "outcome": "pass",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 42,
        }
        return result


class SandboxAwareFakeAndromeda(FakeAndromeda):
    def route(self, **kwargs) -> dict:
        result = super().route(**kwargs)
        result["execution_result"] = {
            "executed_from": "sandbox",
            "outcome": "pass",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 10,
        }
        return result


class ArtifactFakeAndromeda(FakeAndromeda):
    def route(self, **kwargs) -> dict:
        result = super().route(**kwargs)
        result["artifacts"] = [
            {
                "filename": "output.py",
                "content": "x = 1",
                "language": "python",
                "artifact_type": "code",
            }
        ]
        result["writable"] = True
        return result


def test_task_response_includes_execution_result_with_executed_from_workspace(monkeypatch):
    _reset_auth(monkeypatch)
    fake = WorkspaceAwareFakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "Generate a validator", "skill_id": "code_generation"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert "execution_result" in body
    assert body["execution_result"]["executed_from"] == "workspace"


def test_task_response_execution_result_sandbox_mode(monkeypatch):
    _reset_auth(monkeypatch)
    fake = SandboxAwareFakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "Generate a validator", "skill_id": "code_generation"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert "execution_result" in body
    assert body["execution_result"]["executed_from"] == "sandbox"


def test_task_response_workspace_path_null_when_not_configured(monkeypatch):
    _reset_auth(monkeypatch)
    fake = ArtifactFakeAndromeda()
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/task",
            json={"task": "Generate a validator", "skill_id": "code_generation"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_path"] is None
    assert len(body["artifacts"]) >= 1
    assert body["artifacts"][0]["written"] is False
