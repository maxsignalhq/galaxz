"""Constellation: a local catalog of installable declarative YAML agents."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

RESERVED_AGENT_IDS = frozenset(
    {"rigel", "vega", "andromeda", "pulsar", "orion", "aether", "quasar"}
)
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class CatalogError(ValueError):
    pass


class CatalogConflict(CatalogError):
    pass


class CatalogNotFound(CatalogError):
    pass


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _validate(cfg: object, agent_id: str, version: str) -> dict:
    if not isinstance(cfg, dict):
        raise CatalogError("agent.yaml must be a mapping")
    if cfg.get("agent_id") != agent_id:
        raise CatalogError(f"agent_id {cfg.get('agent_id')!r} does not match directory {agent_id!r}")
    if str(cfg.get("version")) != version:
        raise CatalogError(f"version {cfg.get('version')!r} does not match directory {version!r}")
    if not isinstance(cfg.get("agent_name"), str) or not cfg["agent_name"].strip():
        raise CatalogError("agent_name is required")
    skills = cfg.get("skills")
    if not isinstance(skills, list) or not skills:
        raise CatalogError("at least one skill is required")
    for skill in skills:
        if not isinstance(skill, dict):
            raise CatalogError("each skill must be a mapping")
        skill_id = skill.get("skill_id")
        if not isinstance(skill_id, str) or not skill_id.startswith(f"{agent_id}.skill."):
            raise CatalogError(f"skill_id must start with '{agent_id}.skill.': {skill_id!r}")
        if not isinstance(skill.get("description"), str) or not skill["description"].strip():
            raise CatalogError(f"{skill_id}: description is required")
        steps = skill.get("steps")
        if not isinstance(steps, list) or not steps or not all(
            isinstance(s, dict) and isinstance(s.get("user"), str) for s in steps
        ):
            raise CatalogError(f"{skill_id}: steps must be a non-empty list with a 'user' template")
    return cfg


class Catalog:
    def __init__(self, catalog_dir: str | Path | None = None, agents_dir: str | Path | None = None):
        self.catalog_dir = Path(catalog_dir or os.getenv("GALAXZ_CATALOG_DIR", "catalog"))
        self.agents_dir = Path(agents_dir or os.getenv("GALAXZ_AGENTS_DIR", "config/agents"))

    def _versions(self, agent_id: str) -> list[str]:
        folder = self.catalog_dir / agent_id
        if not folder.is_dir():
            return []
        return sorted(
            (p.name for p in folder.iterdir() if _VERSION.match(p.name) and (p / "agent.yaml").is_file()),
            key=_version_key,
        )

    def _load(self, agent_id: str, version: str) -> tuple[dict, str]:
        text = (self.catalog_dir / agent_id / version / "agent.yaml").read_text()
        try:
            cfg = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CatalogError(f"invalid YAML: {exc}") from exc
        return _validate(cfg, agent_id, version), text

    def _installed_version(self, agent_id: str) -> str | None:
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.is_file():
            return None
        try:
            cfg = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            return None
        version = cfg.get("version") if isinstance(cfg, dict) else None
        return str(version) if version is not None else "unknown"

    def list(self) -> list[dict]:
        if not self.catalog_dir.is_dir():
            return []
        entries = []
        for folder in sorted(p for p in self.catalog_dir.iterdir() if p.is_dir()):
            agent_id = folder.name
            versions = self._versions(agent_id)
            if not versions or not _ID.match(agent_id) or agent_id in RESERVED_AGENT_IDS:
                continue
            try:
                cfg, _ = self._load(agent_id, versions[-1])
            except CatalogError as exc:
                logger.warning("[constellation] skipping %s/%s: %s", agent_id, versions[-1], exc)
                continue
            meta = cfg.get("catalog") or {}
            entries.append(
                {
                    "agent_id": agent_id,
                    "agent_name": cfg["agent_name"],
                    "version": versions[-1],
                    "versions": versions,
                    "description": meta.get("description", ""),
                    "author": meta.get("author", ""),
                    "tags": meta.get("tags", []),
                    "skills": [s["skill_id"] for s in cfg["skills"]],
                    "installed_version": self._installed_version(agent_id),
                }
            )
        return entries

    def install(self, agent_id: str, version: str | None = None, force: bool = False) -> dict:
        if not _ID.match(agent_id or ""):
            raise CatalogError("invalid agent_id")
        if agent_id in RESERVED_AGENT_IDS:
            raise CatalogError(f"agent_id {agent_id!r} is reserved for a built-in agent")
        if version is not None and not _VERSION.match(version):
            raise CatalogError("invalid version; expected MAJOR.MINOR.PATCH")
        versions = self._versions(agent_id)
        if not versions:
            raise CatalogNotFound(f"agent {agent_id!r} not found in catalog")
        version = version or versions[-1]
        if version not in versions:
            raise CatalogNotFound(f"version {version!r} of {agent_id!r} not found in catalog")

        _, text = self._load(agent_id, version)
        dest = self.agents_dir / f"{agent_id}.yaml"
        if dest.is_file():
            if dest.read_text() == text:
                return {"agent_id": agent_id, "version": version, "status": "unchanged", "restart_required": False}
            if not force:
                raise CatalogConflict(
                    f"{dest} already exists with different content; pass force to overwrite"
                )
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".yaml.tmp")
        tmp.write_text(text)
        os.replace(tmp, dest)
        return {"agent_id": agent_id, "version": version, "status": "installed", "restart_required": True}
