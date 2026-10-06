"""Wormhole: exposes remote A2A agents' skills as Pulsar skills (`wormhole.<agent>.<skill>`)."""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from core.a2a import protocol
from core.a2a.client import A2AClient, A2AClientError
from core.a2a.config import AgentConfig
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry

logger = logging.getLogger(__name__)

_REMOTE_SKILL_ID = re.compile(r"^[\w.:-]+$")


class WormholeAgent:
    AGENT_ID = "wormhole"
    AGENT_NAME = "Wormhole A2A Gateway"
    VERSION = "0.1.0"

    def __init__(
        self,
        registry: PulsarRegistry,
        agents: list[AgentConfig],
        client_factory: Callable[..., A2AClient] = A2AClient,
    ):
        self._clients: dict[str, A2AClient] = {}
        self._skills: dict[str, tuple[str, str]] = {}  # skill_id -> (agent name, remote skill id)
        self._status: list[dict] = []
        definitions: list[SkillDefinition] = []

        for cfg in agents:
            status = {
                "name": cfg.name,
                "ok": False,
                "error": None,
                "skills": [],
                "allowed_origins": cfg.allowed_origins,
            }
            self._status.append(status)
            client = client_factory(cfg.url, token=cfg.token, timeout_s=cfg.timeout_s)
            try:
                card = client.connect()
            except A2AClientError as exc:
                logger.warning("[wormhole] skipping remote agent %s: %s", cfg.name, exc)
                status["error"] = str(exc)
                client.close()
                continue
            status["ok"] = True
            self._clients[cfg.name] = client
            for remote in card.get("skills") or []:
                remote_id = remote.get("id") if isinstance(remote, dict) else None
                if not isinstance(remote_id, str) or not _REMOTE_SKILL_ID.match(remote_id):
                    logger.warning("[wormhole] %s: skipping skill with invalid id %r", cfg.name, remote_id)
                    continue
                skill_id = f"wormhole.{cfg.name}.{remote_id}"
                description = str(remote.get("description") or "").strip() or remote_id
                self._skills[skill_id] = (cfg.name, remote_id)
                status["skills"].append({"skill_id": skill_id, "description": description})
                definitions.append(
                    SkillDefinition(
                        skill_id=skill_id,
                        description=description,
                        input_schema={},
                        output_schema={},
                        avg_confidence=0.9,
                        allowed_origins=cfg.allowed_origins,
                    )
                )

        if definitions:
            registry.register(
                SkillManifest(
                    agent_id=self.AGENT_ID,
                    agent_name=self.AGENT_NAME,
                    version=self.VERSION,
                    skills=definitions,
                    health_endpoint=f"http://{self.AGENT_ID}:8000/health",
                )
            )
            logger.info("[wormhole] registered with Pulsar — %d remote skills", len(definitions))
        elif registry.get_agent(self.AGENT_ID) is not None:
            # Pulsar persists manifests; don't advertise skills from a previous config.
            registry.deregister(self.AGENT_ID)
            logger.info("[wormhole] no remote skills available — removed stale manifest")

    @property
    def skill_ids(self) -> set[str]:
        return set(self._skills)

    def status(self) -> dict:
        return {"configured": bool(self._status), "agents": self._status}

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        target = self._skills.get(skill_id)
        if target is None:
            raise ValueError(f"{self.AGENT_ID}: unknown skill {skill_id!r}")
        name, remote_id = target
        result = self._clients[name].execute(remote_id, payload)  # A2AClientError fails the task

        succeeded = result.state == protocol.STATE_COMPLETED
        # Binary on purpose: only 1.0 or 0.0, so Andromeda's low-confidence retry rule
        # never re-runs a remote agent that may have side effects.
        confidence = 1.0 if succeeded else 0.0
        gap = result.text or f"remote task ended as {result.state}"
        return {
            "state": result.state,
            "text": result.text,
            "data": result.data,
            "artifacts": [],
            "summary": result.text,
            "writable": False,
            "confidence": confidence,
            "confidence_breakdown": {"structural": confidence, "self_critique": confidence, "historical": 0.50},
            "gaps": [] if succeeded else [gap],
            "execution_result": None,
            "externally_calibrated": False,
        }

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
