"""Outcome-based scoring for automated and human evaluation signals."""

from __future__ import annotations


def score_outcome(*, tests: bool, build: bool, lint: bool, security: bool, acceptance: bool, infrastructure_failure: bool = False, human_decision: str | None = None) -> dict:
    automated = {"tests": tests, "build": build, "lint": lint, "security": security, "acceptance": acceptance}
    if infrastructure_failure:
        quality = None
    else:
        quality = sum(automated.values()) / len(automated)
    return {"quality_score": quality, "automated": automated, "human_decision": human_decision, "infrastructure_failure": infrastructure_failure}
