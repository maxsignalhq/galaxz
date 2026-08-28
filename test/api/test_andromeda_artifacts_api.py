from fastapi.testclient import TestClient

import services.andromeda_service as andromeda_service
from core.artifacts.store import ArtifactStore

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _reset_auth(monkeypatch) -> None:
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    andromeda_service.app.middleware_stack = None


class FakeRegistry:
    def health_check(self) -> dict:
        return {"status": "ok", "skill_count": 0, "agents": []}

    def get_all_skills(self) -> list:
        return []


class FakeAndromedaWithArtifacts:
    def __init__(self, artifact_store) -> None:
        self.artifact_store = artifact_store
        self.registry = FakeRegistry()


def _seeded_store(tmp_path):
    store = ArtifactStore(db_path=str(tmp_path / "artifacts.db"))
    store.record(
        [{"filename": "out.py", "content": "x = 1", "language": "python", "artifact_type": "code"}],
        workspace_root="/ws",
        task_id="task-1",
        skill="rigel.skill.code_generation",
    )
    store.record(
        [{"filename": "out.py", "content": "x = 2", "language": "python", "artifact_type": "code"}],
        workspace_root="/ws",
        task_id="task-2",
        skill="rigel.skill.code_generation",
    )
    return store


def test_list_artifacts_requires_auth(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get("/artifacts")

    assert response.status_code == 401


def test_list_artifacts_returns_latest_versions(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get("/artifacts", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["latest_version"] == 2


def test_history_returns_versions_newest_first(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get(
            "/artifacts/history", params={"path": "out.py", "workspace_root": "/ws"}, headers=AUTH_HEADERS
        )

    assert response.status_code == 200
    body = response.json()
    assert [v["version"] for v in body] == [2, 1]


def test_history_unknown_path_returns_404(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get(
            "/artifacts/history", params={"path": "nope.py", "workspace_root": "/ws"}, headers=AUTH_HEADERS
        )

    assert response.status_code == 404


def test_diff_defaults_to_latest_vs_previous(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get(
            "/artifacts/diff", params={"path": "out.py", "workspace_root": "/ws"}, headers=AUTH_HEADERS
        )

    assert response.status_code == 200
    body = response.json()
    assert "-x = 1" in body["diff"]
    assert "+x = 2" in body["diff"]


def test_diff_missing_version_returns_404(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)

    with TestClient(andromeda_service.app) as client:
        response = client.get(
            "/artifacts/diff",
            params={"path": "out.py", "workspace_root": "/ws", "from": 1, "to": 5},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404


def test_rollback_without_configured_workspace_path_is_not_written(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/artifacts/rollback",
            json={"path": "out.py", "workspace_root": "/ws", "version": 1},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "x = 1"
    assert body["version"] == 1
    assert body["written"] is False


def test_rollback_with_configured_workspace_path_writes_file(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: str(workspace_dir))

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/artifacts/rollback",
            json={"path": "out.py", "workspace_root": "/ws", "version": 1},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["written"] is True
    assert (workspace_dir / "out.py").read_text() == "x = 1"


def test_rollback_missing_version_returns_404(monkeypatch, tmp_path):
    _reset_auth(monkeypatch)
    fake = FakeAndromedaWithArtifacts(_seeded_store(tmp_path))
    monkeypatch.setattr(andromeda_service, "boot", lambda: fake)
    monkeypatch.setattr(andromeda_service, "_read_workspace_path", lambda: "")

    with TestClient(andromeda_service.app) as client:
        response = client.post(
            "/artifacts/rollback",
            json={"path": "out.py", "workspace_root": "/ws", "version": 99},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
