"""Wormhole configuration: inbound callers and outbound remote agents."""
from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

import yaml

logger = logging.getLogger(__name__)

A2A_CONFIG_PATH = "config/a2a.yaml"
_AGENT_NAME = re.compile(r"^[a-z0-9_-]+$")
_ORIGIN_PREFIX = "a2a:"
_DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class CallerConfig:
    token: str
    origin: str
    skills: tuple[str, ...] | None = None

    def allows_skill(self, skill_id: str) -> bool:
        return self.skills is None or any(fnmatchcase(skill_id, p) for p in self.skills)


@dataclass(frozen=True)
class AgentConfig:
    name: str
    url: str
    token: str | None = None
    timeout_s: float = _DEFAULT_TIMEOUT_S
    allowed_origins: list[str] | None = None


@dataclass(frozen=True)
class A2AConfig:
    callers: tuple[CallerConfig, ...] = ()
    agents: tuple[AgentConfig, ...] = ()

    def authenticate(self, authorization: str) -> CallerConfig | None:
        scheme, _, presented = authorization.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return None
        match = None
        for caller in self.callers:  # no early exit: keep timing independent of position
            if hmac.compare_digest(presented.encode(), caller.token.encode()):
                match = caller
        return match


def _string_list(value) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


def _load_caller(entry, environ) -> CallerConfig | None:
    if not isinstance(entry, dict):
        logger.error("[a2a] caller entry must be a mapping — skipped")
        return None
    env_name = entry.get("token_env")
    origin = str(entry.get("origin") or "").strip()
    if not env_name or not origin:
        logger.error("[a2a] caller entry needs token_env and origin — skipped")
        return None
    if not origin.startswith(_ORIGIN_PREFIX):
        logger.error("[a2a] caller origin %r must start with %r — skipped", origin, _ORIGIN_PREFIX)
        return None
    token = (environ.get(env_name) or "").strip()
    if not token:
        logger.warning("[a2a] caller %s ignored: %s is not set", origin, env_name)
        return None
    skills = entry.get("skills")
    if skills is not None:
        skills = _string_list(skills)
        if skills is None:
            logger.error("[a2a] caller %s: skills must be a list of strings — skipped", origin)
            return None
    return CallerConfig(token=token, origin=origin, skills=tuple(skills) if skills is not None else None)


def _load_agent(entry, environ) -> AgentConfig | None:
    if not isinstance(entry, dict):
        logger.error("[a2a] agent entry must be a mapping — skipped")
        return None
    name = str(entry.get("name") or "")
    url = str(entry.get("url") or "").strip().rstrip("/")
    if not _AGENT_NAME.match(name):
        logger.error("[a2a] agent name %r must match [a-z0-9_-]+ — skipped", name)
        return None
    if not url.startswith(("http://", "https://")):
        logger.error("[a2a] agent %s: url must start with http:// or https:// — skipped", name)
        return None
    token = None
    env_name = entry.get("token_env")
    if env_name:
        token = (environ.get(env_name) or "").strip() or None
        if token is None:
            logger.warning("[a2a] agent %s: %s is not set — calling without a token", name, env_name)
    timeout = entry.get("timeout_s", _DEFAULT_TIMEOUT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = _DEFAULT_TIMEOUT_S
    allowed = entry.get("allowed_origins")
    if allowed is not None:
        allowed = _string_list(allowed)
        if allowed is None:
            logger.error("[a2a] agent %s: allowed_origins must be a list of strings — skipped", name)
            return None
    return AgentConfig(name=name, url=url, token=token, timeout_s=float(timeout), allowed_origins=allowed)


def load_a2a_config(path: str = A2A_CONFIG_PATH, environ=None) -> A2AConfig:
    environ = os.environ if environ is None else environ
    if not os.path.exists(path):
        return A2AConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    callers = [c for c in (_load_caller(e, environ) for e in raw.get("callers") or []) if c]
    agents = [a for a in (_load_agent(e, environ) for e in raw.get("agents") or []) if a]
    return A2AConfig(callers=tuple(callers), agents=tuple(agents))
