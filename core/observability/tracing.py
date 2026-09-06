"""Small, exporter-agnostic tracing contract for runtime boundaries."""

from __future__ import annotations

import contextvars
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable


_current: contextvars.ContextVar["Span | None"] = contextvars.ContextVar("galaxz_current_span", default=None)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str | None
    attributes: dict = field(default_factory=dict)
    status: str = "ok"
    duration_ms: int = 0

    def set_status(self, status: str) -> None:
        self.status = status


class Tracer:
    def __init__(self, exporter: Callable[[Span], None] | None = None, sample_rate: float | None = None):
        self.exporter = exporter
        self.sample_rate = float(os.getenv("GALAXZ_TRACE_SAMPLE_RATE", "1")) if sample_rate is None else sample_rate
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("trace sample rate must be between 0 and 1")

    def span(self, name: str, **attributes):
        parent = _current.get()
        sampled = self.sample_rate == 1 or (self.sample_rate > 0 and secrets.randbelow(10_000) < self.sample_rate * 10_000)
        return _SpanContext(self, name, parent, _safe_attributes(attributes), sampled)


def _safe_attributes(attributes: dict) -> dict:
    sensitive = ("prompt", "token", "secret", "password", "authorization", "api_key")
    return {key: "[REDACTED]" if any(item in key.lower() for item in sensitive) else value for key, value in attributes.items()}


class _SpanContext:
    def __init__(self, tracer, name, parent, attributes, sampled):
        self.tracer, self.name, self.parent, self.attributes, self.sampled = tracer, name, parent, attributes, sampled
        self.span = None
        self._token = None

    def __enter__(self):
        if not self.sampled:
            return None
        self.span = Span(self.name, self.parent.trace_id if self.parent else secrets.token_hex(16), secrets.token_hex(8), self.parent.span_id if self.parent else None, self.attributes)
        self._token = _current.set(self.span)
        self._started = time.monotonic()
        return self.span

    def __exit__(self, exc_type, exc, tb):
        if self.span is None:
            return False
        self.span.duration_ms = int((time.monotonic() - self._started) * 1000)
        if exc is not None:
            self.span.status = "error"
        _current.reset(self._token)
        if self.tracer.exporter:
            try:
                self.tracer.exporter(self.span)
            except Exception:
                pass
        return False
