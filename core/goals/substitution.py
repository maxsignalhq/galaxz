from __future__ import annotations

import json
import re
from copy import deepcopy
from uuid import UUID

from core.contracts import PlannedTask


class PayloadResolutionError(ValueError):
    pass


_REFERENCE = re.compile(r"^\$\{\{\s*dependencies\.([0-9a-fA-F-]+)\.result(?:\.([^}]+))?\s*}}$")


def resolve_payload(
    task: PlannedTask,
    dependencies: dict[UUID, PlannedTask],
    *,
    max_bytes: int = 65_536,
) -> dict:
    declared = set(task.depends_on)

    def resolve(value):
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, str):
            return value
        match = _REFERENCE.match(value)
        if match is None:
            return value
        try:
            dependency_id = UUID(match.group(1))
        except ValueError as exc:
            raise PayloadResolutionError("dependency reference contains an invalid UUID") from exc
        if dependency_id not in declared:
            raise PayloadResolutionError(
                f"task {dependency_id} is not a declared dependency"
            )
        dependency = dependencies.get(dependency_id)
        if dependency is None or dependency.result is None:
            raise PayloadResolutionError(f"dependency {dependency_id} has no result")
        current = dependency.result
        path = match.group(2)
        if path:
            for part in path.strip().split("."):
                if not isinstance(current, dict) or part not in current:
                    raise PayloadResolutionError(
                        f"dependency {dependency_id} result has no path {path.strip()}"
                    )
                current = current[part]
        return deepcopy(current)

    resolved = resolve(task.payload)
    if not isinstance(resolved, dict):
        raise PayloadResolutionError("resolved task payload must be an object")
    if len(json.dumps(resolved, separators=(",", ":")).encode()) > max_bytes:
        raise PayloadResolutionError("resolved payload exceeds the configured size limit")
    return resolved
