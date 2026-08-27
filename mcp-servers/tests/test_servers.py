"""The tool plane.

Two kinds of test live here.

**Parity.** The tool gateway enforces scopes against a registry declared in
``backstop_toolgateway.scopes``. If a server grows a tool the registry has never heard
of, that tool is unreachable through the gateway - or, worse, reachable through
some other path with no scope check at all. If the registry declares a tool no
server implements, the gateway advertises a capability that does not exist. Both
are silent failures, so they are asserted.

**Signal visibility.** The synthetic dataset plants abuse patterns and the eval
harness will score whether agents detect them. That only means something if the
signals are actually reachable through the tools, and if the *answers* are not.
Both directions are checked.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from backstop_domain.fraud import FraudPattern
from backstop_mcp.context import dataset, store
from backstop_mcp.servers import catalog, orders, payments, policy, shipping
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

SERVERS: dict[str, MCPServer[Any]] = {
    "orders": orders.server,
    "shipping": shipping.server,
    "catalog": catalog.server,
    "policy": policy.server,
    "payments": payments.server,
}


async def tool_names(server: MCPServer[Any]) -> set[str]:
    return {tool.name for tool in await server.list_tools()}


async def call(server: MCPServer[Any], name: str, **kwargs: Any) -> Any:
    result = await server.call_tool(name, kwargs)
    # call_tool can also return InputRequiredResult, for tools that ask the client
    # a question mid-execution. None of ours do, and one silently starting to
    # would be a change worth failing on.
    assert isinstance(result, CallToolResult), f"{name} asked the client for input"
    assert not result.is_error, f"{name} failed: {result.content}"
    return result.structured_content


async def call_expecting_error(server: MCPServer[Any], name: str, **kwargs: Any) -> str:
    """Invoke a tool that should refuse, and return the message the caller sees.

    ``MCPServer.call_tool`` raises for a deliberate ``ToolError``; the transport
    layer is what turns that into ``CallToolResult(isError=True)`` on the wire.
    Asserting on the message here is asserting on exactly what a client receives,
    because the SDK carries a ``ToolError``'s text through unchanged - and
    suppresses the text of anything else.
    """
    with pytest.raises(ToolError) as caught:
        await server.call_tool(name, kwargs)
    return str(caught.value)


# ---------------------------------------------------------------------------
# Registry parity
# ---------------------------------------------------------------------------


async def test_every_declared_tool_is_implemented() -> None:
    implemented: dict[str, str] = {}
    for server_name, server in SERVERS.items():
        for name in await tool_names(server):
            implemented[name] = server_name

    missing = sorted(set(DEFAULT_REGISTRY.names()) - set(implemented))
    assert not missing, f"declared in the registry but no server implements them: {missing}"


async def test_every_implemented_tool_is_declared() -> None:
    implemented: set[str] = set()
    for server in SERVERS.values():
        implemented |= await tool_names(server)

    undeclared = sorted(implemented - set(DEFAULT_REGISTRY.names()))
    assert not undeclared, (
        f"implemented but not declared in the registry, so unreachable "
        f"through the gateway: {undeclared}"
    )


async def test_each_tool_lives_on_the_server_the_registry_names() -> None:
    for server_name, server in SERVERS.items():
        for name in await tool_names(server):
            spec = DEFAULT_REGISTRY.get(name)
            assert spec is not None
            assert spec.server == server_name, (
                f"{name} is implemented on {server_name} but declared on {spec.server}"
            )


async def test_only_the_payments_server_writes() -> None:
    write_tools = {spec.name for spec in DEFAULT_REGISTRY.write_tools()}
    payments_tools = await tool_names(payments.server)

    assert write_tools <= payments_tools
    for server_name, server in SERVERS.items():
        if server_name == "payments":
            continue
        assert not (await tool_names(server) & write_tools)


async def test_every_tool_is_described_and_typed() -> None:
    """A tool with no description is a tool a model will misuse."""
    for server in SERVERS.values():
        for tool in await server.list_tools():
            assert tool.description, f"{tool.name} has no description"
            assert tool.input_schema.get("type") == "object", tool.name


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def test_get_order_returns_consistent_totals() -> None:
    order = dataset().orders[0]

    payload = await call(orders.server, "get_order", order_id=order.id)

    assert payload["order_id"] == order.id
    assert payload["total"] == str(order.total)
    # Money crosses the wire as a decimal string, never as a float.
    assert isinstance(payload["total"], str)
    assert sum(1 for _ in payload["lines"]) == len(order.lines)


async def test_unknown_order_is_an_error_not_an_empty_result() -> None:
    message = await call_expecting_error(orders.server, "get_order", order_id="ORD-9999999")
    assert "ORD-9999999" in message


async def test_customer_profile_exposes_signals() -> None:
    customer = dataset().customers[0]

    profile = await call(orders.server, "get_customer_profile", customer_id=customer.id)

    for field in (
        "tenure_days",
        "return_rate",
        "never_arrived_claims",
        "accounts_at_this_address",
        "lifetime_value",
    ):
        assert field in profile, field
    assert 0.0 <= profile["return_rate"] <= 1.0


# ---------------------------------------------------------------------------
# Planted patterns are reachable through the tools
# ---------------------------------------------------------------------------


def annotated(pattern: FraudPattern) -> tuple[str, ...]:
    return tuple(
        customer_id
        for annotation in dataset().fraud_annotations
        if annotation.pattern is pattern
        for customer_id in annotation.customer_ids
    )


async def test_a_serial_refunder_shows_an_abnormal_return_rate() -> None:
    suspects = annotated(FraudPattern.SERIAL_REFUNDER)
    assert suspects, "the dataset planted no serial refunders"

    rates = [
        (await call(orders.server, "get_customer_profile", customer_id=customer_id))["return_rate"]
        for customer_id in suspects
    ]

    # The planted cohort returns most of what it buys. If this drifts below the
    # threshold the pattern has stopped being detectable and the eval label is a lie.
    assert min(rates) > 0.5, rates


async def test_an_address_ring_is_visible_as_shared_accounts() -> None:
    ring = annotated(FraudPattern.ADDRESS_REUSE)
    assert ring

    counts = [
        (await call(orders.server, "get_customer_profile", customer_id=customer_id))[
            "accounts_at_this_address"
        ]
        for customer_id in ring
    ]

    assert min(counts) >= 3, counts


async def test_delivery_claim_abuse_is_visible_as_strong_evidence() -> None:
    """Their non-receipt claims sit against deliveries the carrier can prove."""
    suspects = annotated(FraudPattern.DELIVERY_CLAIM_ABUSE)
    assert suspects

    customer_id = suspects[0]
    profile = await call(orders.server, "get_customer_profile", customer_id=customer_id)
    assert profile["never_arrived_claims"] >= 1

    order = store().list_customer_orders(customer_id, limit=1)[0]
    tracking = await call(shipping.server, "track_shipment", order_id=order.id)
    assert tracking["shipment"]["evidence_strength"] == "strong"


async def test_a_high_value_newcomer_reads_as_a_new_account() -> None:
    suspects = annotated(FraudPattern.HIGH_VALUE_NEWCOMER)
    assert suspects

    profile = await call(orders.server, "get_customer_profile", customer_id=suspects[0])
    assert profile["is_new_account"] is True
    assert profile["tenure_days"] < 30


async def test_no_tool_leaks_the_fraud_labels() -> None:
    """Ground truth must never be reachable. An agent that can read the answers
    scores perfectly and tells us nothing."""
    suspects = annotated(FraudPattern.SERIAL_REFUNDER)
    customer_id = suspects[0]

    payloads = [
        await call(orders.server, "get_customer_profile", customer_id=customer_id),
        await call(orders.server, "list_customer_returns", customer_id=customer_id),
        await call(orders.server, "list_customer_orders", customer_id=customer_id),
    ]

    for payload in payloads:
        text = str(payload).lower()
        for pattern in FraudPattern:
            assert pattern.value not in text, f"{pattern.value} leaked into tool output"
        assert "fraud" not in text


# ---------------------------------------------------------------------------
# Shipping and catalogue
# ---------------------------------------------------------------------------


async def test_evidence_strength_follows_the_policy_definition() -> None:
    delivered = next(
        shipment
        for shipment in dataset().shipments
        if shipment.delivered_at and shipment.signature_captured
    )

    payload = await call(shipping.server, "get_delivery_events", shipment_id=delivered.id)

    assert payload["evidence_strength"] == "strong"
    assert payload["events"], "a delivered shipment should have a timeline"


async def test_an_undispatched_order_is_a_state_not_an_error() -> None:
    from backstop_domain.models import OrderStatus

    undispatched = next(
        order for order in dataset().orders if order.status is OrderStatus.CANCELLED
    )

    payload = await call(shipping.server, "track_shipment", order_id=undispatched.id)
    assert payload["shipment"] is None
    assert payload["status"] == "not_dispatched"


async def test_return_eligibility_reports_conditions_not_decisions() -> None:
    order = next(order for order in dataset().orders if order.lines)
    sku = order.lines[0].sku

    payload = await call(catalog.server, "get_return_eligibility", order_id=order.id, sku=sku)

    assert "blocking_conditions" in payload
    # It must not pretend to decide.
    assert "resolution" not in payload
    assert "approved" not in payload


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


async def test_search_returns_versioned_clauses() -> None:
    payload = await call(
        policy.server, "search_policy", query="parcel never arrived signature", limit=3
    )

    assert payload["returned"] > 0
    for hit in payload["results"]:
        assert hit["clause_id"]
        assert hit["document_version"]
        assert hit["text"]


async def test_search_is_capped_regardless_of_what_is_asked_for() -> None:
    payload = await call(policy.server, "search_policy", query="return refund", limit=500)
    assert payload["returned"] <= policy.MAX_RESULTS


async def test_a_clause_can_be_read_verbatim() -> None:
    payload = await call(policy.server, "get_policy_clause", clause_id="RP-4.2")
    assert "48 hours" in payload["text"]
    assert payload["document_id"] == "return-policy"


async def test_a_section_comes_back_whole() -> None:
    payload = await call(policy.server, "get_policy_section", section_id="RP-5")
    ids = [clause["clause_id"] for clause in payload["clauses"]]
    assert "RP-5.3" in ids and "RP-5.4" in ids


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_ledger() -> Any:
    payments.ledger.movements.clear()
    yield
    payments.ledger.movements.clear()


async def test_a_refund_is_recorded() -> None:
    order = dataset().orders[0]

    receipt = await call(
        payments.server,
        "issue_refund",
        order_id=order.id,
        amount_eur="10.00",
        reason="damaged on arrival",
    )

    assert receipt["reference"].startswith("REF-")
    assert receipt["amount_eur"] == "10.00"
    assert receipt["total_refunded_on_order"] == "10.00"


async def test_refunding_more_than_the_order_is_refused() -> None:
    order = dataset().orders[0]

    message = await call_expecting_error(
        payments.server,
        "issue_refund",
        order_id=order.id,
        amount_eur=str(order.total + 1),
        reason="over-refund attempt",
    )
    assert "exceed the order total" in message


async def test_refunds_cannot_accumulate_past_the_order_total() -> None:
    """The realistic version of the bug.

    An agent refunds each line in turn - every call defensible on its own - and
    then, having lost track, refunds the order total as well. Only the last call
    is wrong, and only a running total catches it.
    """
    order = next(order for order in dataset().orders if len(order.lines) >= 2)

    for index, line in enumerate(order.lines, start=1):
        await call(
            payments.server,
            "issue_refund",
            order_id=order.id,
            amount_eur=str(line.line_total),
            reason=f"line {index}",
        )

    message = await call_expecting_error(
        payments.server,
        "issue_refund",
        order_id=order.id,
        amount_eur=str(order.total),
        reason="refunding the whole order, again",
    )
    assert "exceed the order total" in message


async def test_a_negative_refund_is_refused() -> None:
    order = dataset().orders[0]

    message = await call_expecting_error(
        payments.server,
        "issue_refund",
        order_id=order.id,
        amount_eur="-50.00",
        reason="negative",
    )
    assert "greater than zero" in message


async def test_replacement_must_name_an_item_on_the_order() -> None:
    order = dataset().orders[0]

    message = await call_expecting_error(
        payments.server,
        "create_replacement_order",
        order_id=order.id,
        sku="SKU-ZZZ-9999",
        reason="not on this order",
    )
    assert "no line for sku" in message


async def test_movements_are_readable_back() -> None:
    order = dataset().orders[0]
    await call(
        payments.server,
        "issue_refund",
        order_id=order.id,
        amount_eur="5.00",
        reason="goodwill",
    )

    payload = await call(payments.server, "get_movements_for_order", order_id=order.id)
    assert payload["total_refunded"] == "5.00"
    assert len(payload["movements"]) == 1
