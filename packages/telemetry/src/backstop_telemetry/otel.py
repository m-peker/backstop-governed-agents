"""OpenTelemetry wiring.

Every unit of work in Backstop becomes a span: a graph node, a tool gateway call, a
guardrail check, an LLM request. Cost and token counts ride on span attributes so
that "what did this ticket cost" is a trace query rather than a bespoke metric.

Attribute naming follows one convention, declared here so that the dashboards in
``infra/grafana`` can rely on it:

    backstop.ticket_id        the ticket a span belongs to
    backstop.node             the graph node, when applicable
    backstop.tool             the tool name, when applicable
    backstop.model            the resolved model id
    backstop.tokens.input     prompt tokens
    backstop.tokens.output    completion tokens
    backstop.cost_usd         normalised cost across providers
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Tracer

if TYPE_CHECKING:
    from fastapi import FastAPI

ATTR_TICKET_ID: Final = "backstop.ticket_id"
ATTR_NODE: Final = "backstop.node"
ATTR_TOOL: Final = "backstop.tool"
ATTR_MODEL: Final = "backstop.model"
ATTR_TOKENS_IN: Final = "backstop.tokens.input"
ATTR_TOKENS_OUT: Final = "backstop.tokens.output"
ATTR_COST_USD: Final = "backstop.cost_usd"

_configured = False


def setup_tracing(
    *,
    service_name: str,
    environment: str,
    otlp_endpoint: str | None = None,
    console: bool = False,
) -> None:
    """Configure the global tracer provider.

    Idempotent: calling it twice in one process is a no-op, which keeps test
    fixtures and hot reloads from stacking exporters.

    Args:
        service_name: Distinguishes the API from workers and MCP servers.
        environment: ``local``, ``ci``, ``staging`` or ``production``.
        otlp_endpoint: Base OTLP HTTP endpoint. When ``None``, no exporter is
            attached, which is what CI wants.
        console: Also print spans to stdout. Useful while working through the labs.
    """
    global _configured
    if _configured:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"))
        )
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True


def tracer(name: str) -> Tracer:
    """Return a tracer for a module. Safe before :func:`setup_tracing` runs."""
    return trace.get_tracer(name)


def instrument_fastapi(app: FastAPI, *, excluded_urls: str = "health/live,health/ready") -> None:
    """Attach automatic HTTP spans, minus the health probes.

    Health checks fire every few seconds and would otherwise dominate the trace
    store without telling anyone anything.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded_urls)


def current_trace_id() -> str | None:
    """Hex trace id of the active span, or ``None`` outside a trace."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")
