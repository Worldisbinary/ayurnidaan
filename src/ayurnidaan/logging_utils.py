"""Structured JSON logging so pipeline runs are greppable / shippable to a log store."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Set by the API's HTTP middleware for the duration of one request. A ContextVar (not a
# global or thread-local) is correct under both threads and asyncio tasks.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Inside an API request every line carries its ID (set by the HTTP middleware).
        if (rid := request_id_var.get()) is not None:
            payload["request_id"] = rid
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.LoggerAdapter:
    class _Adapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            fields = kwargs.pop("fields", {})
            kwargs.setdefault("extra", {})["extra_fields"] = fields
            return msg, kwargs

    return _Adapter(logging.getLogger(name), {})
