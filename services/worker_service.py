from __future__ import annotations

import logging
import os
import signal
import socket

from boot import boot
from core.contracts import TaskContract
from core.jobs import CancellationToken
from core.jobs import DurableWorker
from core.jobs import WorkerConfig
from core.jobs import PostgresJobRepository
from core.jobs import SqliteJobRepository
from core.jobs.completion import CompletionPublisher
from core.goals import DurableGoalCoordinator
from core.storage.manage import validate_runtime_database_configuration


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def main() -> None:
    validate_runtime_database_configuration()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = os.getenv("GALAXZ_DATABASE_URL") or os.getenv("JOB_DB_PATH", "data/jobs.db")
    repository = PostgresJobRepository(database) if database.startswith(("postgres://", "postgresql://", "postgresql+")) else SqliteJobRepository(database)
    andromeda = boot(os.getenv("GALAXZ_CONFIG_PATH", "config/providers.yaml"))
    coordinator = DurableGoalCoordinator(
        andromeda.goal_store,
        repository,
        review_queue=andromeda.review_queue,
    )
    publisher = CompletionPublisher(repository, andromeda.artifact_store, andromeda.review_queue)

    def reconcile() -> None:
        publisher.publish_pending()
        coordinator.reconcile_all()

    def execute(task: TaskContract, token: CancellationToken) -> dict:
        token.raise_if_cancelled()
        result = andromeda.route(task=task)
        token.raise_if_cancelled()
        return result

    worker = DurableWorker(
        repository,
        execute,
        WorkerConfig(
            worker_id=os.getenv("WORKER_ID", socket.gethostname()),
            concurrency=int(os.getenv("WORKER_CONCURRENCY", "1")),
            lease_seconds=_positive_float("WORKER_LEASE_SECONDS", 30),
            heartbeat_seconds=_positive_float("WORKER_HEARTBEAT_SECONDS", 10),
            poll_seconds=_positive_float("WORKER_POLL_SECONDS", 0.25),
        ),
        cycle_hook=reconcile,
    )
    signal.signal(signal.SIGTERM, lambda signum, frame: worker.request_stop())
    signal.signal(signal.SIGINT, lambda signum, frame: worker.request_stop())
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.shutdown(wait=True)


if __name__ == "__main__":
    main()
