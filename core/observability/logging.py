"""Structured logging with request/job correlation and central redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone

_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("galaxz_log_context", default={})
_SENSITIVE = ("token", "secret", "password", "private_key", "authorization", "api_key")


def get_correlation_context() -> dict[str, str]:
    return dict(_context.get())


@contextmanager
def correlation_context(**values: str):
    merged = {**_context.get(), **{key: str(value) for key, value in values.items() if value is not None}}
    token = _context.set(merged)
    try:
        yield merged
    finally:
        _context.reset(token)


def _redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if any(part in key.lower() for part in _SENSITIVE) else _redact(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {key: value for key, value in record.__dict__.items() if key not in logging.LogRecord(None, 0, "", 0, "", (), None).__dict__ and not key.startswith("_")}
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname, "logger": record.name, "event": record.getMessage(), **get_correlation_context(), **_redact(fields)}
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
