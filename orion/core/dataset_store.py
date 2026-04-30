from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

VALID_DOMAINS = frozenset({"vega", "rigel"})
REQUIRED_EXAMPLE_KEYS = frozenset(
    {
        "prompt",
        "completion",
        "skill_id",
        "confidence",
        "human_verified",
        "task_id",
        "created_at",
    }
)
VERSION_RE = re.compile(r"^v(?P<version>\d+)_\d{4}-\d{2}-\d{2}\.jsonl$")


class DatasetStore:
    def __init__(self, base_path: str = "orion/data/datasets"):
        self.base_path = Path(base_path)
        self.heuristics_path = self.base_path.parent / "heuristics"
        self._buffers: dict[str, list[dict[str, Any]]] = {
            "vega": [],
            "rigel": [],
        }

        for domain in VALID_DOMAINS:
            self._domain_path(domain).mkdir(parents=True, exist_ok=True)
        self.heuristics_path.mkdir(parents=True, exist_ok=True)

    def append_example(self, domain: str, example: dict):
        self._validate_domain(domain)
        missing = REQUIRED_EXAMPLE_KEYS - set(example)
        if missing:
            missing_keys = ", ".join(sorted(missing))
            raise ValueError(f"Example missing required keys: {missing_keys}")
        self._buffers[domain].append(dict(example))

    def flush(self, domain: str) -> str:
        self._validate_domain(domain)
        domain_path = self._domain_path(domain)
        domain_path.mkdir(parents=True, exist_ok=True)

        version = self._next_version(domain)
        path = domain_path / f"v{version}_{date.today().isoformat()}.jsonl"
        examples = self._buffers[domain]

        with path.open("w", encoding="utf-8") as f:
            for example in examples:
                f.write(json.dumps(example, ensure_ascii=False) + "\n")

        latest_path = domain_path / "latest"
        if latest_path.exists() or latest_path.is_symlink():
            latest_path.unlink()
        latest_path.symlink_to(path.name)

        count = len(examples)
        self._buffers[domain] = []
        logger.info(
            "Dataset flushed: %s v%s — %s examples → %s",
            domain,
            version,
            count,
            path,
        )
        return str(path)

    def should_flush(self, domain: str) -> bool:
        self._validate_domain(domain)
        examples = self._buffers[domain]
        human_verified = sum(1 for example in examples if example.get("human_verified"))
        return human_verified >= 100 or len(examples) >= 500

    def get_latest_path(self, domain: str) -> str | None:
        self._validate_domain(domain)
        latest_path = self._domain_path(domain) / "latest"
        if latest_path.is_symlink():
            target = latest_path.readlink()
            if not target.is_absolute():
                target = latest_path.parent / target
            return str(target)

        versions = self._versions(domain)
        if not versions:
            return None
        return str(versions[-1][1])

    def stats(self, domain: str) -> dict:
        self._validate_domain(domain)
        versions = self._versions(domain)
        latest_version = versions[-1][0] if versions else 0
        return {
            "buffered": len(self._buffers[domain]),
            "versions": len(versions),
            "latest_version": latest_version,
            "latest_path": self.get_latest_path(domain),
        }

    def _domain_path(self, domain: str) -> Path:
        return self.base_path / domain

    def _next_version(self, domain: str) -> int:
        versions = self._versions(domain)
        if not versions:
            return 1
        return versions[-1][0] + 1

    def _versions(self, domain: str) -> list[tuple[int, Path]]:
        domain_path = self._domain_path(domain)
        if not domain_path.exists():
            return []

        versions: list[tuple[int, Path]] = []
        for path in domain_path.iterdir():
            if not path.is_file():
                continue
            match = VERSION_RE.match(path.name)
            if match:
                versions.append((int(match.group("version")), path))
        return sorted(versions, key=lambda item: item[0])

    def _validate_domain(self, domain: str) -> None:
        if domain not in VALID_DOMAINS:
            valid = ", ".join(sorted(VALID_DOMAINS))
            raise ValueError(f"Unsupported dataset domain: {domain}. Expected one of: {valid}")
