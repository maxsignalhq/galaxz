import asyncio
import logging
import os

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from agents.vega.agent import VegaAgent
from core.agent_loader import load_yaml_agents
from core.artifacts.object_storage import object_storage_from_environment
from core.artifacts.store import ArtifactStore
from core.pulsar.registry import PulsarRegistry
from core.goals import PostgresGoalStore
from core.storage import PostgresArtifactStore, PostgresReviewQueue, PostgresTaskLog
from core.storage.manage import database_engine, require_current_schema

logger = logging.getLogger(__name__)


def boot(config_path: str = "config/providers.yaml") -> Andromeda:
    """
    Boot sequence (strict order — do not change):
    1. Instantiate PulsarRegistry (loads existing skills from SQLite)
    2. Instantiate TaskLog
    3. Instantiate RigelAgent(registry)
    4. Instantiate VegaAgent(registry) and start its heartbeat loop
    5. Load YAML-defined agents (lumina, pm, etc.)
    6. Instantiate Andromeda(registry, task_log)
    7. Return the Andromeda instance
    """
    registry = PulsarRegistry()
    database_url = os.getenv("GALAXZ_DATABASE_URL")
    if database_url:
        engine = database_engine(database_url)
        try:
            with engine.connect() as connection:
                require_current_schema(connection)
        finally:
            engine.dispose()
        shared_engine = database_engine(database_url)
        task_log = PostgresTaskLog(database_url, engine=shared_engine)
        review_queue = PostgresReviewQueue(database_url, engine=shared_engine)
        artifact_store = PostgresArtifactStore(database_url, engine=shared_engine, object_storage=object_storage_from_environment())
        goal_store = PostgresGoalStore(database_url, engine=shared_engine)
    else:
        task_log = TaskLog()
        review_queue = goal_store = None
        artifact_store = ArtifactStore(object_storage=object_storage_from_environment())
    rigel = RigelAgent(registry, config_path=config_path)
    vega = VegaAgent(registry, config_path=config_path)
    vega.start()
    yaml_agents = load_yaml_agents(registry)
    from orion import OrionService
    from orion.config import OrionConfig
    orion = OrionService(OrionConfig(), registry=registry)
    try:
        asyncio.get_running_loop().create_task(orion.start())
        logger.info("Orion subscribed to Aether.")
    except RuntimeError:
        logger.info("No running event loop; Orion startup deferred.")
    andromeda = Andromeda(
        registry,
        task_log,
        agents={
            rigel.AGENT_ID: rigel,
            vega.AGENT_ID: vega,
            **yaml_agents,
        },
        review_queue=review_queue,
        artifact_store=artifact_store,
        goal_store=goal_store,
    )
    andromeda.orion = orion
    return andromeda


if __name__ == "__main__":
    andromeda = boot()
    print("Galaxz booted.")
    print("Pulsar:", andromeda.registry.health_check())
    print("Rigel:", andromeda.registry.get_all_skills())
