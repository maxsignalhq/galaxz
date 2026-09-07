from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel


class WorkspaceConfig(BaseModel):
    workspace_root: str
    enabled: bool


def write_workspace_config(workspace_root: str, config_path: str = "config/workspace.yaml") -> None:
    """Publish a complete configuration so concurrent workers never read partial YAML."""
    target = Path(config_path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as f:
            temporary_path = Path(f.name)
            yaml.safe_dump({"workspace_root": workspace_root, "enabled": True}, f)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_workspace_config(config_path: str = "config/workspace.yaml") -> WorkspaceConfig:
    if not os.path.exists(config_path):
        return WorkspaceConfig(workspace_root="", enabled=False)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    def resolve(value: object) -> object:
        if not isinstance(value, str):
            return value
        match = re.fullmatch(r"\$\{(\w+)(?::-([^}]*))?\}", value)
        if not match:
            return value
        return os.environ.get(match.group(1), match.group(2) or "")

    workspace_root = resolve(raw.get("workspace_root") or "")
    enabled_value = resolve(raw.get("enabled", False))
    if isinstance(enabled_value, str):
        enabled = enabled_value.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(enabled_value)

    cfg = WorkspaceConfig(
        workspace_root=str(workspace_root),
        enabled=enabled,
    )

    if cfg.enabled:
        if not cfg.workspace_root:
            raise ValueError("workspace_root must not be empty when workspace is enabled")
        if not os.path.isdir(cfg.workspace_root):
            raise ValueError(f"workspace_root does not exist or is not a directory: {cfg.workspace_root}")

    return cfg
