"""Repeatable clean-team onboarding/usability checks."""
from __future__ import annotations

def run_onboarding_checks(results: dict[str, bool]) -> dict:
    checks = {name: bool(passed) for name, passed in results.items()}
    failures = [name for name, passed in checks.items() if not passed]
    return {"status": "passed" if not failures else "blocked", "checks": checks, "failures": failures}
