"""A complete runtime, assembled from real components and one scripted model.

Everything except the model is the production object: the real MCP servers, the
real tool gateway, the real guardrails, the real policy engine. Only the LLM is
scripted, because a test that calls a live model is slow, costs money, and either
flakes or gets weakened until it stops catching anything.

That balance is deliberate. It means these tests exercise the wiring that actually
breaks - a scope that was never granted, a policy rule that does not fire, a
placeholder that never gets resolved - while the model's own behaviour is measured
separately, by the eval harness, against a live provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from backstop_domain.fraud import FraudPattern
from backstop_graph import Runtime, compile_graph, initial_state
from backstop_graph.schemas import (
    Assessment,
    Classification,
    ProposedResolution,
    ReplyDraft,
    TicketIntent,
)
from backstop_guardrails import InputGuardrail, turkish_name_gazetteer
from backstop_llm import LLMClient, Message, StubProvider, stub_policy
from backstop_mcp.bridge import local_handlers
from backstop_mcp.context import dataset, store
from backstop_mcp.servers import payments
from backstop_policy import PolicyEngine
from backstop_toolgateway import ApprovalAuthority, StaticPolicy, ToolGateway
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

SECRET = "graph-test-secret-16-plus"
CEILING = Decimal("75.00")


@pytest.fixture(autouse=True)
def _clean_ledger() -> None:
    payments.ledger.movements.clear()


@pytest.fixture
def stub() -> StubProvider:
    return StubProvider()


@pytest.fixture
def llm(stub: StubProvider) -> LLMClient:
    return LLMClient(providers={"stub": stub}, policy=stub_policy())


@pytest.fixture
async def runtime(llm: LLMClient) -> Runtime:
    gateway = ToolGateway(
        registry=DEFAULT_REGISTRY,
        handlers=await local_handlers(),
        approvals=(approvals := ApprovalAuthority(SECRET)),
        policy=StaticPolicy(ceiling=CEILING),
    )
    return Runtime(
        gateway=gateway,
        llm=llm,
        policy=PolicyEngine(),
        input_guard=InputGuardrail(known_names=turkish_name_gazetteer()),
        approvals=approvals,
        auto_approve_ceiling=CEILING,
    )


@pytest.fixture
def graph(runtime: Runtime) -> Any:
    return compile_graph(runtime, checkpointer=InMemorySaver())


@pytest.fixture
def config() -> dict[str, Any]:
    return {"configurable": {"thread_id": "TCK-GRAPH-1"}}


# ---------------------------------------------------------------------------
# Scripting helpers
# ---------------------------------------------------------------------------


def script_model(
    stub: StubProvider,
    *,
    intent: TicketIntent = TicketIntent.DAMAGED_ON_ARRIVAL,
    order_id: str | None = None,
    requests_human: bool = False,
    resolution: ProposedResolution = ProposedResolution.FULL_REFUND,
    amount: str | None = "40.00",
    clauses: Sequence[str] = ("RP-4.1",),
    confidence: float = 0.92,
    needs_human: bool = False,
    concerns: Sequence[str] = (),
    reply: str = "We are sorry your order arrived damaged. A refund is on its way.",
) -> StubProvider:
    """Script all three model calls the graph makes on the happy path."""
    stub.script(
        Classification,
        Classification(
            intent=intent,
            confidence=0.95,
            order_id=order_id,
            requests_human=requests_human,
            summary="Customer reports a problem with their order.",
        ),
    )
    stub.script(
        Assessment,
        Assessment(
            resolution=resolution,
            amount_eur=amount,
            confidence=confidence,
            cited_clauses=list(clauses),
            rationale="The facts and the cited clauses support this resolution.",
            needs_human=needs_human,
            concerns=list(concerns),
        ),
    )
    stub.script(ReplyDraft, ReplyDraft(reply=reply, tone="apologetic", mentions_amount=True))
    return stub


def prompts_seen(stub: StubProvider, schema: type[BaseModel]) -> str:
    """Everything sent to the model for one schema. For asserting on prompts."""
    for name, messages in stub.calls:
        if name == schema.__name__:
            return "\n".join(message.content for message in messages)
    raise AssertionError(f"the model was never asked for {schema.__name__}")


def all_messages(stub: StubProvider) -> list[Message]:
    return [message for _, messages in stub.calls for message in messages]


# ---------------------------------------------------------------------------
# Scenario data
# ---------------------------------------------------------------------------


def pick_order(
    *,
    min_total: Decimal | None = None,
    max_days_since_delivery: int | None = 2,
) -> Any:
    """An order suitable for a given scenario.

    ``max_days_since_delivery`` defaults to 2 because most tests want the
    *uncomplicated* case, and in this domain "uncomplicated" includes being inside
    RP-4.2's 48-hour damage-reporting window. An order delivered three years ago
    engages the planted AMB-01 conflict and correctly routes to a human - useful
    behaviour, but not what a test of the happy path is trying to exercise.
    """
    for order in dataset().orders:
        shipment = store().get_shipment_for_order(order.id)
        if shipment is None or shipment.delivered_at is None:
            continue
        if min_total is not None and order.total < min_total:
            continue
        if max_days_since_delivery is not None:
            elapsed = (store().reference_date - shipment.delivered_at).days
            if elapsed > max_days_since_delivery:
                continue
        return order
    raise AssertionError("no order in the dataset matches those constraints")


def pick_evidenced_non_receipt() -> tuple[str, str]:
    """A customer from the delivery-claim cohort, and one of their orders.

    The carrier holds a signature and a photo, so RP-5.3 refers rather than settles.
    """
    suspects = [
        customer_id
        for annotation in dataset().fraud_annotations
        if annotation.pattern is FraudPattern.DELIVERY_CLAIM_ABUSE
        for customer_id in annotation.customer_ids
    ]
    customer_id = suspects[0]
    return customer_id, store().list_customer_orders(customer_id, limit=1)[0].id


def start(message: str, *, ticket_id: str = "TCK-GRAPH-1", channel: str = "email") -> Any:
    return initial_state(ticket_id=ticket_id, message=message, channel=channel)
