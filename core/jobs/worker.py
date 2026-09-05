from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from core.contracts import JobStatus
from core.contracts import TaskContract

from .repository import InvalidJobState
from .repository import LeaseConflict
from .repository import SqliteJobRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerConfig:
    worker_id: str
    concurrency: int = 1
    lease_seconds: float = 30.0
    heartbeat_seconds: float = 10.0
    poll_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self.lease_seconds <= 0 or self.heartbeat_seconds <= 0:
            raise ValueError("lease and heartbeat intervals must be positive")
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat interval must be shorter than the lease")
        if self.poll_seconds <= 0:
            raise ValueError("poll interval must be positive")


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled("job cancellation requested")

    def cancel(self) -> None:
        self._event.set()


class JobCancelled(RuntimeError):
    pass


class RetryableExecutionError(RuntimeError):
    def __init__(self, message: str, *, error_code: str = "transient") -> None:
        super().__init__(message)
        self.error_code = error_code


Executor = Callable[[TaskContract, CancellationToken], dict]


class DurableWorker:
    """Claims durable jobs and executes them without owning API request threads."""

    def __init__(
        self,
        repository: SqliteJobRepository,
        executor: Executor,
        config: WorkerConfig,
        cycle_hook: Callable[[], None] | None = None,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.config = config
        self.cycle_hook = cycle_hook
        self._stopping = threading.Event()
        self._pool = ThreadPoolExecutor(
            max_workers=config.concurrency,
            thread_name_prefix=f"job-{config.worker_id}",
        )
        self._active: set[Future[None]] = set()

    def run_forever(self) -> None:
        logger.info(
            "worker_ready",
            extra={"worker_id": self.config.worker_id, "concurrency": self.config.concurrency},
        )
        try:
            while not self._stopping.is_set():
                self.run_cycle()
                self._stopping.wait(self.config.poll_seconds)
        finally:
            self.shutdown(wait=True)

    def run_cycle(self) -> bool:
        """Reclaim expired leases and start at most one available job."""
        if self.cycle_hook is not None:
            self.cycle_hook()
        self._active = {future for future in self._active if not future.done()}
        reclaimed = self.repository.reclaim_expired()
        for job in reclaimed:
            logger.warning(
                "job_lease_recovered",
                extra={"worker_id": self.config.worker_id, "job_id": str(job.job_id)},
            )
        if self._stopping.is_set() or len(self._active) >= self.config.concurrency:
            return bool(reclaimed)
        claimed = self.repository.claim(
            worker_id=self.config.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if claimed is None:
            return bool(reclaimed)
        job, attempt = claimed
        future = self._pool.submit(
            self._execute,
            job.job_id,
            attempt.attempt_id,
            attempt.attempt_number,
            attempt.lease_token,
        )
        self._active.add(future)
        return True

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop claiming first, then drain active attempts when requested."""
        self._stopping.set()
        self._pool.shutdown(wait=wait, cancel_futures=False)

    def request_stop(self) -> None:
        """Signal the claim loop to stop; active attempts continue draining."""
        self._stopping.set()

    def _execute(
        self,
        job_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        lease_token: UUID,
    ) -> None:
        task = self.repository.get_task(job_id)
        context = {
            "worker_id": self.config.worker_id,
            "job_id": str(job_id),
            "attempt_id": str(attempt_id),
            "attempt_number": attempt_number,
        }
        if task is None:
            self.repository.record_failure(
                job_id=job_id,
                lease_token=lease_token,
                error="persisted task input is missing",
                error_code="invalid_input",
                retryable=False,
            )
            logger.error("job_failed", extra=context)
            return

        token = CancellationToken()
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job_id, lease_token, token, heartbeat_stop),
            name=f"heartbeat-{attempt_id}",
            daemon=True,
        )
        heartbeat.start()
        logger.info("job_started", extra=context)
        try:
            execution_task = task.model_copy(update={"execution_attempt_id": attempt_id})
            result = self.executor(execution_task, token)
            token.raise_if_cancelled()
            self.repository.complete(
                job_id=job_id,
                lease_token=lease_token,
                output_ref=f"job-output:{job_id}",
                result=result,
            )
            logger.info("job_completed", extra=context)
        except JobCancelled:
            logger.info("job_cancelled", extra=context)
        except RetryableExecutionError as exc:
            self._record_failure(job_id, lease_token, exc, exc.error_code, True, context)
        except (LeaseConflict, InvalidJobState):
            logger.warning("job_late_result_discarded", extra=context)
        except Exception as exc:
            self._record_failure(job_id, lease_token, exc, "permanent", False, context)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=self.config.heartbeat_seconds * 2)

    def _record_failure(
        self,
        job_id: UUID,
        lease_token: UUID,
        exc: Exception,
        error_code: str,
        retryable: bool,
        context: dict,
    ) -> None:
        try:
            self.repository.record_failure(
                job_id=job_id,
                lease_token=lease_token,
                error=str(exc),
                error_code=error_code,
                retryable=retryable,
            )
            logger.exception("job_execution_failed", extra=context)
        except (LeaseConflict, InvalidJobState):
            logger.warning("job_late_failure_discarded", extra=context)

    def _heartbeat(
        self,
        job_id: UUID,
        lease_token: UUID,
        token: CancellationToken,
        stop: threading.Event,
    ) -> None:
        while not stop.wait(self.config.heartbeat_seconds):
            job = self.repository.get_job(job_id)
            if job is None or job.status is JobStatus.cancelled:
                token.cancel()
                return
            try:
                self.repository.heartbeat(
                    job_id=job_id,
                    lease_token=lease_token,
                    lease_seconds=self.config.lease_seconds,
                )
            except (LeaseConflict, InvalidJobState):
                token.cancel()
                return
