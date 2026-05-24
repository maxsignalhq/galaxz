import os
import textwrap

import pytest

from workspace.config import WorkspaceConfig, load_workspace_config


# ── Test 1 ──────────────────────────────────────────────────────────────────
def test_disabled_config_accepts_empty_workspace_root():
    cfg = WorkspaceConfig(enabled=False, workspace_root="")
    assert cfg.enabled is False
    assert cfg.workspace_root == ""


# ── Test 2 ──────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_with_valid_path(tmp_path):
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        textwrap.dedent(f"""\
            workspace_root: "{project_dir}"
            enabled: true
        """)
    )

    cfg = load_workspace_config(str(config_file))

    assert cfg.enabled is True
    assert cfg.workspace_root == str(project_dir)


# ── Test 3a ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_empty_root_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text("workspace_root: ''\nenabled: true\n")

    with pytest.raises(ValueError, match="workspace_root must not be empty"):
        load_workspace_config(str(config_file))


# ── Test 3b ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_missing_path_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        "workspace_root: '/does/not/exist/xyz'\nenabled: true\n"
    )

    with pytest.raises(ValueError, match="workspace_root does not exist"):
        load_workspace_config(str(config_file))


# ── Missing file ─────────────────────────────────────────────────────────────
def test_load_workspace_config_missing_file_returns_disabled_default(tmp_path):
    cfg = load_workspace_config(str(tmp_path / "no_such_file.yaml"))

    assert cfg.enabled is False
    assert cfg.workspace_root == ""
