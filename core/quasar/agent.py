"""Quasar: exposes MCP server tools as Pulsar skills (`quasar.<server>.<tool>`)."""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import yaml

from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry
from core.quasar.client import McpError, McpStdioClient

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = "config/mcp.yaml"


def load_mcp_config(path: str = MCP_CONFIG_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("servers") or []


class QuasarAgent:
    AGENT_ID = "quasar"
    AGENT_NAME = "Quasar MCP Tool Manager"
    VERSION = "0.1.0"

    def __init__(
        self,
        registry: PulsarRegistry,
        servers: list[dict],
        client_factory: Callable[..., McpStdioClient] = McpStdioClient,
    ):
        self._clients: dict[str, McpStdioClient] = {}
        self._skills: dict[str, tuple[str, str]] = {}  # skill_id -> (server, tool)
        definitions: list[SkillDefinition] = []

        for server in servers:
            name = server["name"]
            client = client_factory(
                server["command"], env=server.get("env"), timeout_s=server.get("timeout_s", 30.0)
            )
            try:
                tools = client.list_tools()
            except McpError as exc:
                logger.warning("[quasar] skipping MCP server %s: %s", name, exc)
                client.close()
                continue
            self._clients[name] = client
            for tool in tools:
                skill_id = f"quasar.{name}.{tool['name']}"
                self._skills[skill_id] = (name, tool["name"])
                definitions.append(
                    SkillDefinition(
                        skill_id=skill_id,
                        description=tool.get("description") or tool["name"],
                        input_schema=tool.get("inputSchema") or {},
                        output_schema={},
                        avg_confidence=0.9,
                        allowed_origins=server.get("allowed_origins"),
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
            logger.info("[quasar] registered with Pulsar — %d tools", len(definitions))

    @property
    def skill_ids(self) -> set[str]:
        return set(self._skills)

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        target = self._skills.get(skill_id)
        if target is None:
            raise ValueError(f"{self.AGENT_ID}: unknown skill {skill_id!r}")
        server, tool = target
        result = self._clients[server].call_tool(tool, payload)

        content = result.get("content", [])
        is_error = bool(result.get("isError"))
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        # Binary signal on purpose: only 1.0 or 0.0, so Andromeda's low-confidence
        # retry rule never re-runs a tool that may have side effects.
        confidence = 0.0 if is_error else 1.0
        return {
            "content": content,
            "is_error": is_error,
            "artifacts": [],
            "summary": text,
            "writable": False,
            "confidence": confidence,
            "confidence_breakdown": {"structural": confidence, "self_critique": confidence, "historical": 0.50},
            "gaps": [text] if is_error else [],
            "execution_result": None,
            "externally_calibrated": False,
        }

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
