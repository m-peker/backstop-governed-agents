"""Observability bootstrap shared by every Backstop process.

Two concerns live here and nowhere else:

* :func:`setup_tracing` wires OpenTelemetry once per process.
* :func:`setup_logging` configures structlog so that every log line carries the
  active trace and span id.

Keeping both in one package means an agent node, an MCP server and the API all
emit correlatable telemetry without repeating the wiring.
"""

from backstop_telemetry.logging import get_logger, setup_logging
from backstop_telemetry.otel import instrument_fastapi, setup_tracing, tracer

__all__ = [
    "get_logger",
    "instrument_fastapi",
    "setup_logging",
    "setup_tracing",
    "tracer",
]
