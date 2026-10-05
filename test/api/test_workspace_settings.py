from pathlib import Path

import pytest
from fastapi import HTTPException

import services.andromeda_service as svc
from workspace.config import load_workspace_config


@pytest.fixture
def settings_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GALAXZ_WORKSPACE_HOST_PATH", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/providers.yaml").write_text("llm:\n  model: old\n")
    (tmp_path / "config/workspace.yaml").write_text("enabled: false\nworkspace_root: ''\n")
    return tmp_path


def test_workspace_save_is_visible_to_next_load(settings_dir):
    target = settings_dir / "new"
    target.mkdir()
    svc.update_config(svc.ConfigUpdateRequest(workspace_path=str(target)))
    assert load_workspace_config().workspace_root == str(target)
    assert svc.get_config()["workspace_path"] == str(target)


def test_invalid_workspace_does_not_partially_change_model(settings_dir):
    providers = Path("config/providers.yaml").read_bytes()
    workspace = Path("config/workspace.yaml").read_bytes()
    with pytest.raises(HTTPException) as exc:
        svc.update_config(svc.ConfigUpdateRequest(model="changed", workspace_path=str(settings_dir / "missing")))
    assert exc.value.status_code == 422
    assert Path("config/providers.yaml").read_bytes() == providers
    assert Path("config/workspace.yaml").read_bytes() == workspace


def test_host_path_outside_mount_is_rejected(settings_dir, monkeypatch):
    monkeypatch.setenv("GALAXZ_WORKSPACE_HOST_PATH", "/host/mounted")
    with pytest.raises(HTTPException) as exc:
        svc.update_config(svc.ConfigUpdateRequest(workspace_path="/host/other"))
    assert exc.value.status_code == 422


def test_task_response_uses_workspace_snapshot_not_new_settings(settings_dir, monkeypatch):
    old = settings_dir / "old"
    new = settings_dir / "new"
    old.mkdir()
    new.mkdir()
    svc.update_config(svc.ConfigUpdateRequest(workspace_path=str(new)))
    monkeypatch.setattr(svc, "_normalize_skill_id", lambda skill: skill)
    monkeypatch.setattr(svc, "_route_one", lambda *args: {
        "status": "complete", "context": {"workspace_root": str(old)},
        "writable": True, "artifacts": [{"filename": "a.py", "content": "x = 1"}],
    })
    response = svc.post_task(svc.TaskRequest(task="generate", skill_id="code_generation"))
    assert response["workspace_path"] == str(old)
    assert response["artifacts"][0]["content"] == "x = 1"
    assert response["artifacts"][0]["written"] is True
    assert (old / "a.py").read_text() == "x = 1"
    assert not (new / "a.py").exists()


def test_workspace_display_path_matches_host_mount(monkeypatch):
    monkeypatch.setenv("GALAXZ_WORKSPACE_HOST_PATH", "/host/projects")
    assert svc._workspace_display_path("/workspace/default_workspace/a.py") == "/host/projects/default_workspace/a.py"
    assert svc._workspace_display_path("/workspace-other/a.py") == "/workspace-other/a.py"
