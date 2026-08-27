"""When the room sits, and what it is allowed to do when it does.

The routing question these tests pin down is narrow but load-bearing: a case that
needs a person because a *rule* says so goes straight to the approval queue, and a
case that needs a person because the *policy contradicts itself* is argued first.
Getting that backwards would either burn a debate on every large refund, or hand
reviewers the hard cases with no argument attached.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import pick_order, script_model, start
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backstop_deliberation import DeliberationRoom
from backstop_graph import Runtime, Status, compile_graph
from backstop_graph.schemas import (
    DeliberationTurn,
    DeliberationVerdict,
    ProposedResolution,
    TicketIntent,
)
from backstop_llm import LLMClient, StubProvider
from backstop_mcp.servers import payments

# An order delivered long ago. Reporting damage now engages AMB-01: RP-4.2 sets a
# 48-hour reporting deadline and attaches no consequence to missing it, while
# RP-4.1 grants the remedy unconditionally.
LATE_DAMAGE_TICKET = (
    "Merhaba, {order} numarali siparisimdeki vazo kirik cikti. Simdi fark ettim. Iade istiyorum."
)


def script_room(stub: StubProvider) -> None:
    stub.script(
        DeliberationTurn,
        DeliberationTurn(
            argument="RP-4.2 sets a reporting deadline but attaches no consequence to it.",
            cited_clauses=["RP-4.2"],
            recommends=ProposedResolution.FULL_REFUND,
        ),
    )
    stub.script(
        DeliberationVerdict,
        DeliberationVerdict(
            resolution=ProposedResolution.FULL_REFUND,
            amount_eur="40.00",
            cited_clauses=["RP-4.1"],
            rationale="RP-4.1 grants the remedy without a time limit of its own.",
            dissent="RP-4.2 may be read as a condition rather than an internal deadline.",
            confidence=0.6,
        ),
    )


@pytest.fixture
def graph_with_room(runtime: Runtime, llm: LLMClient) -> Any:
    """The same graph, with the deliberation room wired in."""
    from dataclasses import replace

    return compile_graph(
        replace(runtime, room=DeliberationRoom(llm, max_messages=3)),
        checkpointer=InMemorySaver(),
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def test_a_policy_contradiction_convenes_the_room(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")
    script_room(stub)

    result = await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)

    assert "__interrupt__" in result
    request = result["__interrupt__"][0].value
    assert request["deliberation"] is not None
    assert request["deliberation"]["skipped"] is False


async def test_the_reviewer_receives_both_sides_and_the_dissent(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    """The point of convening the room: the reviewer does not have to construct
    the counter-argument themselves."""
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")
    script_room(stub)

    result = await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)
    deliberation = result["__interrupt__"][0].value["deliberation"]

    assert deliberation["dissent"]
    assert deliberation["transcript"]
    assert deliberation["cited_clauses"]


async def test_a_plain_ceiling_case_skips_the_room(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    """An amount over the ceiling has nothing to argue about."""
    from decimal import Decimal

    order = pick_order(min_total=Decimal("200"))
    script_model(stub, order_id=order.id, amount="150.00")
    script_room(stub)

    result = await graph_with_room.ainvoke(
        start(f"Siparisim {order.id} kirik geldi, iade istiyorum."), config
    )

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["deliberation"] is None
    # And no debate was held, so no deliberation call was billed.
    assert "deliberate" not in stub_tasks(stub)


def stub_tasks(stub: StubProvider) -> set[str]:
    return {name for name, _ in stub.calls}


async def test_the_room_never_executes(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    """There is no edge from deliberate to execute. That absence is the guarantee."""
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")
    script_room(stub)

    await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)

    assert payments.ledger.movements == []


async def test_the_human_still_decides_after_the_room(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")
    script_room(stub)

    await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)
    final = await graph_with_room.ainvoke(
        Command(resume={"approved": False, "approver": "ops.supervisor"}), config
    )

    assert final["status"] == Status.REJECTED.value
    assert payments.ledger.movements == []


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_without_a_room_the_case_still_reaches_a_person(
    graph: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    """No room configured is a degradation, not a failure - and it says so."""
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")

    result = await graph.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)

    assert "__interrupt__" in result
    deliberation = result["__interrupt__"][0].value["deliberation"]
    assert deliberation["skipped"] is True
    assert "unargued" in deliberation["reason"]


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


async def test_the_debate_lands_in_the_tickets_cost(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any], llm: LLMClient
) -> None:
    """A debate that runs long shows up in the per-ticket cost rather than hiding."""
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, amount="40.00")
    script_room(stub)

    await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)

    breakdown = llm.ledger.breakdown()
    assert "deliberate" in breakdown
    assert "arbitrate" in breakdown


async def test_the_classified_intent_decides_nothing_on_its_own(
    graph_with_room: Any, stub: StubProvider, config: dict[str, Any]
) -> None:
    """A sanity check on the fixture: the routing came from the policy engine,
    not from the intent label."""
    order = pick_order(max_days_since_delivery=None)
    script_model(stub, order_id=order.id, intent=TicketIntent.DAMAGED_ON_ARRIVAL, amount="40.00")
    script_room(stub)

    result = await graph_with_room.ainvoke(start(LATE_DAMAGE_TICKET.format(order=order.id)), config)

    rules = {
        ruling["rule_id"] for ruling in result["policy_decision"]["rulings"] if ruling["ambiguous"]
    }
    assert "R-DAMAGE-LATE-REPORT" in rules
