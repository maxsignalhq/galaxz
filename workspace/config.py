from __future__ import annotations

import os

import yaml
from pydantic import BaseModel


class WorkspaceConfig(BaseModel):
    workspace_root: str
    enabled: bool


def load_workspace_config(config_path: str = "config/workspace.yaml") -> WorkspaceConfig:
    if not os.path.exists(config_path):
        return WorkspaceConfig(workspace_root="", enabled=False)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = WorkspaceConfig(
        workspace_root=raw.get("workspace_root", ""),
        enabled=bool(raw.get("enabled", False)),
    )

    if cfg.enabled:
        if not cfg.workspace_root:
            raise ValueError("workspace_root must not be empty when workspace is enabled")
        if not os.path.exists(cfg.workspace_root):
            raise ValueError(f"workspace_root does not exist: {cfg.workspace_root}")

    return cfg
