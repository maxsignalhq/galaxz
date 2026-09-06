"""Hash-verifiable immutable review evidence packages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewEvidencePackage:
    request: dict
    resolved_payload: dict
    base_sha: str
    diff_hash: str
    artifacts: list[dict]
    validation: dict
    confidence: dict
    agent: str
    model: str
    prompt: str
    attempt_id: str

    def as_dict(self) -> dict:
        value = {"request": self.request, "resolved_payload": self.resolved_payload, "base_sha": self.base_sha,
                 "diff_hash": self.diff_hash, "artifacts": self.artifacts, "validation": self.validation,
                 "confidence": self.confidence, "agent": self.agent, "model": self.model,
                 "prompt": self.prompt, "attempt_id": self.attempt_id}
        value["package_hash"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return value

    @staticmethod
    def verify(package: dict) -> bool:
        supplied = package.get("package_hash")
        body = {key: value for key, value in package.items() if key != "package_hash"}
        expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return bool(supplied and supplied == expected)
