"""The adapter between the MCP servers and the tool gateway.

The seam these tests protect: the gateway must be able to drive the real servers
without knowing anything about MCP, and the registry must be the only thing that
decides what is callable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backstop_mcp.bridge import local_handlers
from backstop_mcp.context import dataset
from backstop_mcp.servers import payments
from backstop_toolgateway import (
    ApprovalAuthority,
    ApprovalRequired,
    ScopeDenied,
    StaticPolicy,
    ToolGateway,
)
from backstop_toolgateway.principal import (
    DELIBERATION_FRAUD_INVESTIGATOR,
    GRAPH_EXECUTOR,
    GRAPH_INVESTIGATOR,
)
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

SECRET = "bridge-test-secret-16-plus"
TICKET = "TCK-BRIDGE"


@pytest.fixture(autouse=True)
def _clean_ledger() -> None:
    payments.ledger.movements.clear()


@pytest.fixture
async def gateway() -> ToolGateway:
    return ToolGateway(
        registry=DEFAULT_REGISTRY,
        handlers=await local_handlers(),
        approvals=ApprovalAuthority(SECRET),
        policy=StaticPolicy(ceiling=Decimal("75.00")),
    )


async def test_the_bridge_covers_every_declared_tool() -> None:
    handlers = await local_handlers()
    assert set(DEFAULT_REGISTRY.names()) <= set(handlers)


async def test_the_gateway_accepts_the_bridge_without_complaint() -> None:
    """Construction rejects handlers for undeclared tools, so this is a real check."""
    ToolGateway(
        registry=DEFAULT_REGISTRY,
        handlers=await local_handlers(),
        approvals=ApprovalAuthority(SECRET),
    )


async def test_a_read_flows_through_to_the_real_server(gateway: ToolGateway) -> None:
    order = dataset().orders[0]

    result = await gateway.invoke(
        principal=GRAPH_INVESTIGATOR,
        ticket_id=TICKET,
        tool="get_order",
        args={"order_id": order.id},
    )

    assert result.value["order_id"] == order.id
    assert result.value["total"] == str(order.total)


async def test_a_small_refund_reaches_the_payments_ledger(gateway: ToolGateway) -> None:
    order = dataset().orders[0]

    await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": order.id, "amount_eur": "10.00", "reason": "damaged"},
    )

    assert len(payments.ledger.movements) == 1
    assert payments.ledger.total_refunded(order.id) == Decimal("10.00")


async def test_a_large_refund_is_stopped_before_the_server_sees_it(
    gateway: ToolGateway,
) -> None:
    """The gateway refuses first, so the ledger records nothing at all."""
    order = next(order for order in dataset().orders if order.total > 200)

    with pytest.raises(ApprovalRequired):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": order.id, "amount_eur": "200.00", "reason": "large"},
        )

    assert payments.ledger.movements == []


async def test_scope_is_enforced_before_the_server_is_reached(gateway: ToolGateway) -> None:
    order = dataset().orders[0]

    with pytest.raises(ScopeDenied):
        await gateway.invoke(
            principal=DELIBERATION_FRAUD_INVESTIGATOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": order.id, "amount_eur": "5.00", "reason": "should not happen"},
        )

    assert payments.ledger.movements == []


async def test_a_server_side_refusal_surfaces_as_a_gateway_failure(
    gateway: ToolGateway,
) -> None:
    """An integrity refusal from the server is still a failed invocation."""
    from backstop_toolgateway import ToolExecutionFailed

    order = dataset().orders[0]

    with pytest.raises(ToolExecutionFailed):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": order.id, "amount_eur": "-1.00", "reason": "negative"},
        )

    # Recorded as a failure, and the reason is kept for an operator.
    entry = gateway.audit.entries[-1]
    assert entry.outcome.value == "failed"
    assert "greater than zero" in entry.detail


async def test_the_double_refund_is_prevented_end_to_end(gateway: ToolGateway) -> None:
    """The property the whole gateway exists for, against the real payments server."""
    order = dataset().orders[0]
    args = {"order_id": order.id, "amount_eur": "10.00", "reason": "damaged"}

    first = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args
    )
    second = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args
    )

    assert second.replayed is True
    assert second.value == first.value
    assert len(payments.ledger.movements) == 1
    gateway.audit.verify()
