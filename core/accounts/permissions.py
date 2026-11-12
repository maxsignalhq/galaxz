"""Roles, permissions and the route -> permission table.

A route that is not declared here requires ``admin`` (fail closed). The guard test in
``test/api/test_accounts_api.py`` fails when an app route has no declaration.
"""

from __future__ import annotations

import re

READ = "read"
WORK_WRITE = "work:write"
REVIEW_DECIDE = "review:decide"
AUDIT_READ = "audit:read"
ADMIN = "admin"

ROLES: dict[str, frozenset[str]] = {
    "viewer": frozenset({READ}),
    "operator": frozenset({READ, WORK_WRITE}),
    "reviewer": frozenset({READ, REVIEW_DECIDE}),
    "admin": frozenset({READ, WORK_WRITE, REVIEW_DECIDE, AUDIT_READ, ADMIN}),
}

_SEG = r"[^/]+"

# (method, path regex, permission) — first match wins.
_RULES: tuple[tuple[str, str, str], ...] = (
    # human review decisions
    ("POST", rf"/review/queue/{_SEG}/(accept|approve|reject)", REVIEW_DECIDE),
    ("POST", rf"/finetune/candidates/{_SEG}/(approve|reject)", REVIEW_DECIDE),
    ("POST", rf"/lessons/{_SEG}/(approve|reject)", REVIEW_DECIDE),
    ("POST", rf"/tasks/{_SEG}/feedback", REVIEW_DECIDE),
    # day-to-day work
    ("POST", r"/task", WORK_WRITE),
    ("POST", r"/jobs", WORK_WRITE),
    ("POST", rf"/jobs/{_SEG}/cancel", WORK_WRITE),
    ("POST", r"/goals", WORK_WRITE),
    ("POST", rf"/goals/{_SEG}/(cancel|pause|resume)", WORK_WRITE),
    ("POST", rf"/goals/{_SEG}/tasks/{_SEG}/rerun", WORK_WRITE),
    ("POST", r"/memory", WORK_WRITE),
    ("DELETE", rf"/memory/{_SEG}", WORK_WRITE),
    ("POST", r"/artifacts/rollback", WORK_WRITE),
    ("POST", r"/lessons/propose", WORK_WRITE),
    ("POST", r"/orion/training/run", WORK_WRITE),
    # audit
    ("GET", r"/audit/(events|verify)", AUDIT_READ),
    # administration
    ("GET", r"/config", ADMIN),
    ("POST", r"/config", ADMIN),
    ("POST", r"/repositories", ADMIN),
    ("POST", rf"/catalog/{_SEG}/install", ADMIN),
    ("POST", r"/forge/(agent|skill)", ADMIN),  # writes Python source under agents/, like a catalog install
    ("POST", r"/github/(pull-request|check-run)", ADMIN),
    ("GET", r"/github/installations(/.*)?", ADMIN),
    ("GET", r"/orion/export", ADMIN),  # the full training dataset
    ("GET", r"/(openapi\.json|docs|docs/oauth2-redirect|redoc)", ADMIN),  # FastAPI built-ins
    # read-only views
    ("GET", r"/auth/me", READ),
    ("GET", r"/artifacts(/(diff|history))?", READ),
    ("GET", r"/agents", READ),
    ("GET", r"/catalog", READ),
    ("GET", r"/finetune/candidates", READ),
    ("GET", r"/goals(/.*)?", READ),
    ("GET", r"/jobs(/.*)?", READ),
    ("GET", r"/lessons", READ),
    ("GET", r"/memory(/namespaces)?", READ),
    ("GET", r"/orion/analytics", READ),
    ("GET", r"/quasar", READ),
    ("GET", rf"/repositories/{_SEG}", READ),
    ("GET", r"/review/queue(/.*)?", READ),
    ("GET", r"/scorecards(/.*)?", READ),
    ("GET", r"/status", READ),
    ("GET", r"/tasks/(recent|stats|throughput)", READ),
    ("GET", r"/wormhole", READ),
)

# Routes an organization other than ``default`` may call. Everything else is platform-wide (the audit
# chain, provider/workspace config, scaffolding, Orion's stores, GitHub installation listings) and is
# refused for other organizations, so a new route fails closed until it is scoped and listed here.
_TENANT_RULES: tuple[tuple[str, str], ...] = (
    ("GET", r"/auth/me"),
    ("POST", r"/task"),
    ("POST", r"/jobs"),
    ("GET", r"/jobs(/.*)?"),
    ("POST", rf"/jobs/{_SEG}/cancel"),
    ("POST", r"/goals"),
    ("GET", r"/goals(/.*)?"),
    ("POST", rf"/goals/{_SEG}/(cancel|pause|resume)"),
    ("POST", rf"/goals/{_SEG}/tasks/{_SEG}/rerun"),
    ("GET", r"/review/queue(/.*)?"),
    ("POST", rf"/review/queue/{_SEG}/(accept|approve|reject)"),
    ("POST", rf"/tasks/{_SEG}/feedback"),
    ("GET", r"/tasks/(recent|stats|throughput)"),
    ("GET", r"/status"),
    ("POST", r"/memory"),
    ("GET", r"/memory(/namespaces)?"),
    ("DELETE", rf"/memory/{_SEG}"),
    ("GET", r"/artifacts(/(diff|history))?"),
    ("POST", r"/artifacts/rollback"),
    ("POST", r"/repositories"),
    ("GET", rf"/repositories/{_SEG}"),
    ("POST", r"/github/(pull-request|check-run)"),
    # shared platform resources, read-only
    ("GET", r"/agents"),
    ("GET", r"/catalog"),
    ("GET", r"/quasar"),
    ("GET", r"/wormhole"),
    ("GET", r"/(openapi\.json|docs|docs/oauth2-redirect|redoc)"),
)
_TENANT_COMPILED = tuple((method, re.compile(pattern)) for method, pattern in _TENANT_RULES)

_COMPILED = tuple((method, re.compile(pattern), permission) for method, pattern, permission in _RULES)


def declared_permission(method: str, path: str) -> str | None:
    method = method.upper()
    for rule_method, pattern, permission in _COMPILED:
        if rule_method == method and pattern.fullmatch(path):
            return permission
    return None


def tenant_scoped(method: str, path: str) -> bool:
    """True when the route is safe for an organization other than ``default``."""
    method = method.upper()
    return any(rule_method == method and pattern.fullmatch(path) for rule_method, pattern in _TENANT_COMPILED)


def required_permission(method: str, path: str) -> str:
    return declared_permission(method, path) or ADMIN


def allows(role: str, permission: str) -> bool:
    return permission in ROLES.get(role, frozenset())
