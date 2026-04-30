import os
import re
import threading
from pathlib import Path
from typing import Optional

import yaml

from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry_store import RegistryStore
from core.pulsar.sqlite_store import SqliteStore

_DEFAULT_DB_PATH = "data/pulsar.db"
_STORAGE_CONFIG = Path(__file__).parent / "config" / "storage.yaml"


def _resolve_env(value: str) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), value)


def _storage_config() -> dict:
    if not _STORAGE_CONFIG.exists():
        return {}

    with _STORAGE_CONFIG.open() as f:
        return yaml.safe_load(f) or {}


def storage_backend_summary() -> dict[str, str]:
    cfg = _storage_config()
    backend = cfg.get("backend", "sqlite")
    if backend == "sqlite":
        return {"backend": "sqlite", "path": cfg.get("sqlite_path", _DEFAULT_DB_PATH)}
    if backend in ("postgres", "postgresql"):
        return {"backend": "postgres"}
    return {"backend": str(backend)}


def _store_from_config() -> SqliteStore:
    if not _STORAGE_CONFIG.exists():
        return SqliteStore(os.environ.get("PULSAR_DB_URL"))

    cfg = _storage_config()
    backend = cfg.get("backend", "sqlite")
    if backend == "sqlite":
        path = cfg.get("sqlite_path", _DEFAULT_DB_PATH)
        return SqliteStore(f"sqlite://{path}")
    elif backend in ("postgres", "postgresql"):
        dsn = _resolve_env(cfg.get("postgres_dsn", "")) or os.environ.get("PULSAR_DB_URL", "")
        return SqliteStore(dsn)
    else:
        raise ValueError(f"Unknown storage backend: {backend!r}. Valid: sqlite, postgres")


class PulsarRegistry:
    """
    Skill registry. In-memory dict as primary lookup.
    Persistence backend configured via core/pulsar/config/storage.yaml.
    Thread-safe via a single threading.Lock.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self._lock = threading.Lock()
        self._agents: dict[str, SkillManifest] = {}

        # Explicit db_path (e.g. tests) → always SQLite at that path.
        # Default db_path → read storage.yaml for backend config.
        if db_path == _DEFAULT_DB_PATH:
            self._store: RegistryStore = _store_from_config()
        else:
            self._store = SqliteStore(f"sqlite://{db_path}")

        for agent_dict in self._store.list_agents():
            manifest = SkillManifest.model_validate(agent_dict)
            self._agents[manifest.agent_id] = manifest

    def register(self, manifest: SkillManifest) -> None:
        with self._lock:
            self._agents[manifest.agent_id] = manifest
            self._store.register_agent(manifest.agent_id, manifest.model_dump(mode="json"))

    def get_agents_for_skill(self, skill_id: str) -> list[SkillManifest]:
        with self._lock:
            return [
                agent
                for agent in self._agents.values()
                if any(skill.skill_id == skill_id for skill in agent.skills)
            ]

    def get_agent(self, agent_id: str) -> Optional[SkillManifest]:
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self) -> list[SkillManifest]:
        with self._lock:
            return list(self._agents.values())

    def get_all_skills(self) -> list[SkillDefinition]:
        with self._lock:
            skills: list[SkillDefinition] = []
            for agent in self._agents.values():
                skills.extend(agent.skills)
            return skills

    def deregister(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
            self._store.deregister_agent(agent_id)

    def health_check(self) -> dict:
        with self._lock:
            agents = sorted(self._agents)
            skill_count = sum(len(agent.skills) for agent in self._agents.values())
            return {"status": "ok", "skill_count": skill_count, "agents": agents}
