"""Config-driven agent loader.

Reads YAML files from config/agents/*.yaml and instantiates a GenericLLMAgent
for each. Rigel and Vega are not loaded here — they have custom Python logic.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from core.contracts import SkillDefinition, SkillManifest
from core.llm.provider import call_llm, load_provider_config
from core.pulsar.registry import PulsarRegistry

logger = logging.getLogger(__name__)

AGENTS_CONFIG_DIR = Path("config/agents")


def _render(template: str, vars: dict) -> str:
    """Simple {key} substitution that doesn't choke on user content."""
    result = template
    for key, value in vars.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def _strip_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
    return "\n".join(lines[1:end]).strip()


class GenericLLMAgent:
    def __init__(self, cfg: dict, registry: PulsarRegistry, config_path: str = "config/providers.yaml"):
        self._cfg = cfg
        self._provider_config = load_provider_config(config_path)
        self.AGENT_ID = cfg["agent_id"]
        self.AGENT_NAME = cfg["agent_name"]
        self.VERSION = cfg.get("version", "0.1.0")
        # Build skill lookup
        self._skills: dict[str, dict] = {s["skill_id"]: s for s in cfg["skills"]}
        self._register_manifest(registry)

    def _register_manifest(self, registry: PulsarRegistry) -> None:
        skill_defs = [
            SkillDefinition(
                skill_id=s["skill_id"],
                description=s["description"],
                input_schema={},
                output_schema={},
                avg_confidence=s.get("avg_confidence", 0.80),
                avg_latency_ms=s.get("avg_latency_ms", 1000),
            )
            for s in self._cfg["skills"]
        ]
        manifest = SkillManifest(
            agent_id=self.AGENT_ID,
            agent_name=self.AGENT_NAME,
            version=self.VERSION,
            skills=skill_defs,
            health_endpoint=f"http://{self.AGENT_ID}:8000/health",
            heartbeat_interval_s=30,
            metadata={"color": self._cfg.get("color", "#94a3b8")},
        )
        registry.register(manifest)
        logger.info("[%s] registered with Pulsar — %d skills", self.AGENT_ID, len(skill_defs))

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        skill_cfg = self._skills.get(skill_id)
        if skill_cfg is None:
            raise ValueError(f"{self.AGENT_ID}: unknown skill {skill_id!r}")

        defaults = skill_cfg.get("payload_defaults", {})
        vars = {**defaults, **payload}

        steps = skill_cfg.get("steps", [])
        if not steps:
            raise ValueError(f"{self.AGENT_ID}/{skill_id}: no steps defined")

        artifacts = []
        for step in steps:
            system = _render(step.get("system", ""), vars)
            user = _render(step.get("user", ""), vars)
            text, _, _ = call_llm(
                [{"role": "user", "content": user}],
                self._provider_config,
                system_prompt=system,
            )
            if step.get("strip_fences", False):
                text = _strip_fences(text)
            else:
                text = text.strip()

            filename = _render(step.get("artifact_filename", "output.txt"), vars)
            artifacts.append({
                "filename": filename,
                "content": text,
                "language": step.get("artifact_language", "text"),
                "artifact_type": step.get("artifact_type", "report"),
            })

        summary_tpl = skill_cfg.get("summary_template", "")
        summary = _render(summary_tpl, vars) if summary_tpl else ""
        avg_confidence = skill_cfg.get("avg_confidence", 0.80)

        return {
            "artifacts": artifacts,
            "summary": summary,
            "writable": skill_cfg.get("writable", False),
            "confidence": avg_confidence,
            "confidence_breakdown": {
                "structural": avg_confidence,
                "self_critique": avg_confidence,
                "historical": 0.50,
            },
            "gaps": [],
            "execution_result": None,
            "externally_calibrated": False,
        }


def load_yaml_agents(
    registry: PulsarRegistry,
    config_path: str = "config/providers.yaml",
    agents_dir: Path = AGENTS_CONFIG_DIR,
) -> dict[str, GenericLLMAgent]:
    agents: dict[str, GenericLLMAgent] = {}
    if not agents_dir.exists():
        logger.warning("agents config dir %s not found — no YAML agents loaded", agents_dir)
        return agents

    for yaml_path in sorted(agents_dir.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(yaml_path.read_text())
            agent = GenericLLMAgent(cfg, registry, config_path)
            agents[agent.AGENT_ID] = agent
            logger.info("Loaded YAML agent: %s from %s", agent.AGENT_ID, yaml_path.name)
        except Exception:
            logger.exception("Failed to load YAML agent from %s", yaml_path)

    return agents
