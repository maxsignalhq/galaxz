"""Default-deny execution input and resource policy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceLimits:
    cpu: float = 0.5
    memory: str = "256m"
    pids: int = 64
    timeout_seconds: int = 30
    output_bytes: int = 1_000_000


@dataclass(frozen=True)
class ExecutionPolicy:
    allowed_commands: tuple[str, ...] = ("python",)
    allowed_environment: tuple[str, ...] = ("PYTHONDONTWRITEBYTECODE",)
    limits: ResourceLimits = ResourceLimits()
    network_mode: str = "deny-all"

    def validate_command(self, command: list[str]) -> None:
        if not command or command[0] not in self.allowed_commands:
            raise PolicyDenied("command is not allowed", "command")
        if any("$" in part or "`" in part or ";" in part for part in command):
            raise PolicyDenied("shell interpolation is not allowed", "command")

    def validate_environment(self, environment: dict[str, str]) -> dict[str, str]:
        denied = sorted(set(environment) - set(self.allowed_environment))
        if denied:
            raise PolicyDenied("environment variable is not allowed", "environment", denied)
        return dict(environment)

    def validate_path(self, root: str | Path, path: str | Path) -> Path:
        root_path = Path(root).resolve()
        candidate = Path(path)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root_path):
            raise PolicyDenied("path escapes workspace", "filesystem")
        if candidate.exists() and candidate.is_symlink() and not resolved.is_relative_to(root_path):
            raise PolicyDenied("symlink escapes workspace", "filesystem")
        if candidate.exists() and candidate.is_file() and not os.access(candidate, os.R_OK):
            raise PolicyDenied("file is not readable", "filesystem")
        return resolved


class PolicyDenied(PermissionError):
    def __init__(self, message: str, policy: str, details: list[str] | None = None):
        super().__init__(message)
        self.policy = policy
        self.details = details or []

    def as_dict(self) -> dict:
        return {"error": "policy_denied", "policy": self.policy, "message": str(self), "details": self.details}
