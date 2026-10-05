"""Pre-action authorization: decide, before an agent runs, whether a task may proceed."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from fnmatch import fnmatchcase

import yaml

POLICY_PATH_ENV = "GALAXZ_POLICY_PATH"
DEFAULT_POLICY_PATH = "config/policy.yaml"

ALLOW = "allow"
DENY = "deny"
REQUIRE_REVIEW = "require_review"
_RULE_ACTIONS = (DENY, REQUIRE_REVIEW)
_SEVERITY = {ALLOW: 0, REQUIRE_REVIEW: 1, DENY: 2}
_RULE_KEYS = {"skill", "origin", "action", "reason"}


class PolicyConfigError(ValueError):
    """The policy file is unusable. Raised instead of running with a weaker policy."""


@dataclass(frozen=True)
class PolicyRule:
    skill: str
    action: str
    origin: str = "*"
    reason: str = ""

    def matches(self, skill: str, origin: str) -> bool:
        return fnmatchcase(skill, self.skill) and fnmatchcase(origin, self.origin)


@dataclass(frozen=True)
class PolicyDecision:
    action: str = ALLOW
    reason: str = ""
    rule_index: int | None = None


class PolicyEngine:
    def __init__(self, rules: tuple[PolicyRule, ...] = ()):
        self.rules = tuple(rules)

    @property
    def enabled(self) -> bool:
        return bool(self.rules)

    def evaluate_skill(self, skill: str, origin: str | None) -> PolicyDecision:
        origin = origin or ""
        for index, rule in enumerate(self.rules):
            if rule.matches(skill, origin):
                return PolicyDecision(rule.action, rule.reason or f"policy rule {index}", index)
        return PolicyDecision()

    def evaluate(self, skills: list[str], origin: str | None) -> PolicyDecision:
        """Strictest decision across skills; the first rule wins within one skill."""
        strictest = PolicyDecision()
        for skill in skills:
            decision = self.evaluate_skill(skill, origin)
            if _SEVERITY[decision.action] > _SEVERITY[strictest.action]:
                strictest = decision
        return strictest


def payload_digest(origin: str | None, skill: str, payload: dict) -> str:
    canonical = json.dumps({"origin": origin or "", "skill": skill, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_rule(index: int, entry) -> PolicyRule:
    where = f"rule {index}"
    if not isinstance(entry, dict):
        raise PolicyConfigError(f"{where}: must be a mapping")
    unknown = sorted(set(entry) - _RULE_KEYS)
    if unknown:
        raise PolicyConfigError(f"{where}: unknown keys {unknown}")
    skill = entry.get("skill")
    if not isinstance(skill, str) or not skill.strip():
        raise PolicyConfigError(f"{where}: skill is required")
    action = entry.get("action")
    if action not in _RULE_ACTIONS:
        raise PolicyConfigError(f"{where}: action must be one of {list(_RULE_ACTIONS)}")
    origin = entry.get("origin", "*")
    if not isinstance(origin, str) or not origin.strip():
        raise PolicyConfigError(f"{where}: origin must be a non-empty string")
    reason = entry.get("reason", "")
    if not isinstance(reason, str):
        raise PolicyConfigError(f"{where}: reason must be a string")
    return PolicyRule(skill=skill.strip(), action=action, origin=origin.strip(), reason=reason.strip())


def load_policy(path: str | None = None) -> PolicyEngine:
    path = path or os.getenv(POLICY_PATH_ENV) or DEFAULT_POLICY_PATH
    if not os.path.exists(path):
        return PolicyEngine()
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise PolicyConfigError(f"{path}: invalid YAML ({exc.__class__.__name__})") from None
    if not isinstance(raw, dict):
        raise PolicyConfigError(f"{path}: top level must be a mapping")
    rules = raw.get("rules")
    if rules is None:
        return PolicyEngine()
    if not isinstance(rules, list):
        raise PolicyConfigError(f"{path}: rules must be a list")
    return PolicyEngine(tuple(_parse_rule(i, entry) for i, entry in enumerate(rules)))
