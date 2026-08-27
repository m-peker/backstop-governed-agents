"""Structured logging.

Three rules the whole codebase depends on:

1. Logs are JSON everywhere except a developer's terminal. A governance dossier is
   assembled from structured events, not from grepped prose.
2. Every line carries ``trace_id`` so a log and a span can be joined. The processor
   below injects it automatically, so no call site has to remember.
3. There is exactly one log stream. Application events and third-party output
   (uvicorn, sqlalchemy, httpx) go through the same renderer, so a container never
   emits two competing formats.

Rule 3 is why this routes structlog through the standard library rather than
printing directly: ``ProcessorFormatter`` lets foreign log records pass through the
same processor chain as native structlog events.

Secret and PII redaction is deliberately *not* handled here. Nothing that reaches a
logger should contain either. The guardrail plane tokenises personal data before it
enters the pipeline, and sensitive references live in the audit log under access
control.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

from backstop_telemetry.otel import current_trace_id

_NOISY_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "sqlalchemy.engine",
)


def _add_trace_id(
    _logger: Any,
    _method: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    trace_id = current_trace_id()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def setup_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog and route standard-library logging through it.

    Args:
        level: Root log level name.
        json_output: JSON lines when true, coloured console output when false.
            Local development sets this to false; everything else leaves it true.
    """
    numeric_level = logging.getLevelNamesMapping()[level.upper()]

    # Applied to native structlog events and, via ``foreign_pre_chain``, to
    # records emitted by libraries that know nothing about structlog.
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_trace_id,
    ]

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Libraries that install their own handlers would otherwise bypass the
    # formatter above and print in their own shape.
    for name in _NOISY_LOGGERS:
        noisy = logging.getLogger(name)
        noisy.handlers.clear()
        noisy.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Call this at module level."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
