"""Build A2A Agent Cards from the Pulsar registry."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from typing import Callable

from core.a2a import protocol
from core.a2a.config import CallerConfig
from core.contracts import SkillDefinition
from core.pulsar.registry import PulsarRegistry

AGENT_CARD_PATH = "/.well-known/agent-card.json"
_JSON = "application/json"
# Never re-export remote agents we merely proxy: it would publish third parties'
# skills and let two Galaxz instances call each other in a loop.
_PROXY_AGENT_ID = "wormhole"


def _platform_version() -> str:
    try:
        return _package_version("galaxz")
    except PackageNotFoundError:
        return "0.0.0"


def _skill_entry(skill: SkillDefinition) -> dict:
    return {
        "id": skill.skill_id,
        "name": skill.skill_id,
        "description": skill.description,
        "tags": [skill.skill_id.split(".")[0]],
        "inputModes": [_JSON],
        "outputModes": [_JSON],
    }


def _collect(registry: PulsarRegistry, allowed: Callable[[SkillDefinition], bool]) -> list[dict]:
    seen: dict[str, SkillDefinition] = {}
    for manifest in registry.list_agents():
        if manifest.agent_id == _PROXY_AGENT_ID:
            continue
        for skill in manifest.skills:
            if skill.skill_id not in seen and allowed(skill):
                seen[skill.skill_id] = skill
    return [_skill_entry(seen[skill_id]) for skill_id in sorted(seen)]


def _card(base_url: str, skills: list[dict]) -> dict:
    return {
        "name": "Galaxz",
        "description": (
            "Galaxz multi-agent platform. To run a skill, send a data part "
            '{"skill": "<skill id>", "payload": {...}}.'
        ),
        "version": _platform_version(),
        "supportedInterfaces": [
            {
                "url": f"{base_url.rstrip('/')}/a2a",
                "protocolBinding": protocol.BINDING,
                "protocolVersion": protocol.A2A_VERSION,
            }
        ],
        "capabilities": {"streaming": True, "pushNotifications": False, "extendedAgentCard": True},
        "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "defaultInputModes": [_JSON],
        "defaultOutputModes": [_JSON],
        "skills": skills,
    }


def build_public_card(registry: PulsarRegistry, base_url: str) -> dict:
    return _card(base_url, _collect(registry, lambda s: s.allowed_origins is None))


def build_extended_card(registry: PulsarRegistry, base_url: str, caller: CallerConfig) -> dict:
    return _card(
        base_url,
        _collect(registry, lambda s: s.permits(caller.origin) and caller.allows_skill(s.skill_id)),
    )
