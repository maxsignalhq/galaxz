import asyncio
import logging

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from agents.vega.agent import VegaAgent
from core.agent_loader import load_yaml_agents
from core.pulsar.registry import PulsarRegistry

logger = logging.getLogger(__name__)


def boot() -> Andromeda:
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
    task_log = TaskLog()
    rigel = RigelAgent(registry)
    vega = VegaAgent(registry)
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
    )
    andromeda.orion = orion
    return andromeda


if __name__ == "__main__":
    andromeda = boot()
    print("Galaxz booted.")
    print("Pulsar:", andromeda.registry.health_check())
    print("Rigel:", andromeda.registry.get_all_skills())
