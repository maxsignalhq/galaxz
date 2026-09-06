"""Versioned repository benchmark fixture registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkFixture:
    name: str
    language: str
    base_commit: str
    workflow: str
    acceptance: tuple[str, ...]
    hidden_tests: tuple[str, ...]

    def validate(self) -> None:
        if len(self.base_commit) != 40 or any(char not in "0123456789abcdef" for char in self.base_commit):
            raise ValueError("fixture base_commit must be an immutable SHA")
        if not self.acceptance or not self.hidden_tests:
            raise ValueError("fixture requires acceptance criteria and hidden tests")


def load_fixtures(path: str | Path = "test/fixtures/benchmarks.json") -> list[BenchmarkFixture]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fixtures = [BenchmarkFixture(item["name"], item["language"], item["base_commit"], item["workflow"], tuple(item["acceptance"]), tuple(item["hidden_tests"])) for item in payload]
    for fixture in fixtures:
        fixture.validate()
    return fixtures
