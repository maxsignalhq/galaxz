from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class RoutingWeightsLoader:
    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        self.reload()

    def get_weights(self, skill_id: str) -> dict:
        weights = self._data.get("weights", {}).get(skill_id, {})
        if not isinstance(weights, dict):
            return {}
        return {
            str(agent_id): float(weight)
            for agent_id, weight in weights.items()
        }

    def reload(self):
        raw = self.path.read_text(encoding="utf-8")
        data = yaml.safe_load(_normalize_inline_mapping_spacing(raw)) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Routing weights file must contain a mapping: {self.path}")
        self._data = data
        return self

    def is_cold_start(self, skill_id: str) -> bool:
        return self.last_version() == 0

    def last_version(self) -> int:
        return int(self._data.get("version", 0))

    @property
    def source(self) -> str:
        return str(self._data.get("source", "unknown"))


def _normalize_inline_mapping_spacing(raw: str) -> str:
    return re.sub(r"^(\s*[^:#\n][^:\n]*):(?=\{)", r"\1: ", raw, flags=re.MULTILINE)
