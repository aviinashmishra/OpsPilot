"""Structured logging with correlation IDs and secret redaction."""

from __future__ import annotations

import contextvars
import logging
import re
import sys
from typing import Any

import structlog

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
tenant_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)

_SECRET_KEYS = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key|cookie)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.=]+", re.IGNORECASE)


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively redact secret-looking keys and bearer tokens from log payloads."""
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if isinstance(k, str) and _SECRET_KEYS.search(k) else redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, str):
        return _BEARER.sub(r"\1***", value)
    return value


def _add_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    cid = correlation_id_var.get()
    tid = tenant_id_var.get()
    if cid:
        event_dict.setdefault("correlation_id", cid)
    if tid:
        event_dict.setdefault("tenant_id", tid)
    return event_dict


def _redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return redact(event_dict)


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    # Never render traceback locals: frames hold Settings, API keys and request payloads, which
    # the redaction processor cannot see because they are formatted after it runs.
    exc_formatter = structlog.dev.RichTracebackFormatter(show_locals=False) if getattr(structlog.dev, "rich", None) else structlog.dev.plain_traceback
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer(exception_formatter=exc_formatter)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_context,
            _redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
