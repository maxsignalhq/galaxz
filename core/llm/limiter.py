import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SLOW_WAIT_S = 1.0


class LLMQueueTimeout(RuntimeError):
    """Raised when no provider slot frees up within the queue wait limit."""


class _Slot:
    def __init__(self, max_concurrent: int) -> None:
        self.semaphore = threading.BoundedSemaphore(max_concurrent)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.waiting = 0


class ProviderLimiter:
    """Caps in-flight calls per provider key within this process.

    A slot is released when the worker finishes, not when the caller stops
    waiting: a client-side timeout leaves the call running on the provider, so
    it must keep counting against the cap.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {}

    def _slot(self, key: str, max_concurrent: int) -> _Slot:
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = self._slots[key] = _Slot(max_concurrent)
            return slot

    def submit(
        self,
        key: str,
        max_concurrent: int,
        queue_timeout_s: float,
        fn: Callable[..., Any],
        **kwargs: Any,
    ) -> Future:
        slot = self._slot(key, max_concurrent)
        started = time.monotonic()
        with self._lock:
            slot.waiting += 1
        try:
            acquired = slot.semaphore.acquire(timeout=queue_timeout_s)
        finally:
            with self._lock:
                slot.waiting -= 1
        waited = time.monotonic() - started
        if not acquired:
            raise LLMQueueTimeout(f"LLM queue wait timed out after {queue_timeout_s:.1f} seconds")
        if waited > _SLOW_WAIT_S:
            logger.debug("LLM call for %s waited %.1fs for a slot (%d still queued)", key, waited, slot.waiting)
        try:
            future = slot.executor.submit(fn, **kwargs)
        except BaseException:
            slot.semaphore.release()
            raise
        future.add_done_callback(lambda _f: slot.semaphore.release())
        return future
