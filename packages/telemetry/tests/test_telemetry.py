"""Telemetry bootstrap behaviour."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backstop_telemetry import setup_tracing, tracer
from backstop_telemetry.otel import ATTR_COST_USD, ATTR_TICKET_ID, current_trace_id


def test_setup_tracing_is_idempotent() -> None:
    setup_tracing(service_name="test", environment="ci")
    setup_tracing(service_name="test", environment="ci")

    # A second call must not stack a second provider, otherwise every span in a
    # hot-reloaded dev process would be exported twice.
    from opentelemetry import trace

    assert isinstance(trace.get_tracer_provider(), TracerProvider)


def test_current_trace_id_is_none_outside_a_span() -> None:
    assert current_trace_id() is None


def test_spans_carry_the_agreed_backstop_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with provider.get_tracer(__name__).start_as_current_span("assess") as span:
        span.set_attribute(ATTR_TICKET_ID, "TCK-1001")
        span.set_attribute(ATTR_COST_USD, 0.0042)
        assert current_trace_id() is not None

    (recorded,) = exporter.get_finished_spans()
    assert recorded.attributes is not None
    assert recorded.attributes[ATTR_TICKET_ID] == "TCK-1001"
    assert recorded.attributes[ATTR_COST_USD] == 0.0042


def test_tracer_is_usable_before_setup() -> None:
    assert tracer("anything") is not None
