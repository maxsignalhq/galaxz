"""Deterministic release evaluation gate for production candidates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseEvidence:
    tests_passed: bool
    security_passed: bool
    benchmark_passed: bool
    rollback_verified: bool
    unresolved_critical_findings: int = 0


def evaluate_release(evidence: ReleaseEvidence) -> dict:
    checks = {
        "tests": evidence.tests_passed,
        "security": evidence.security_passed,
        "benchmarks": evidence.benchmark_passed,
        "rollback": evidence.rollback_verified,
        "critical_findings": evidence.unresolved_critical_findings == 0,
    }
    return {"status": "approved" if all(checks.values()) else "blocked", "checks": checks}
