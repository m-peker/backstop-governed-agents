"""Resolve one ticket by hand, through the real capability boundary.

Phase 1 has no agents yet. This script stands in for the resolution graph that
arrives in Phase 2 and walks the same path a graph node would: gather facts,
retrieve policy, attempt to act, hit the approval gate, resume with a signed
approval, and survive a replay.

Nothing here is mocked. The MCP servers are the real servers, the gateway is the
real gateway, and the audit chain printed at the end is the real record.

Run it with::

    uv run python scripts/demo_ticket.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from typing import Any

from backstop_domain.fraud import FraudPattern
from backstop_mcp.bridge import local_handlers
from backstop_mcp.context import dataset, store
from backstop_toolgateway import (
    ApprovalAuthority,
    ApprovalRequired,
    GatewayError,
    Principal,
    StaticPolicy,
    ToolGateway,
)
from backstop_toolgateway.principal import (
    DELIBERATION_CUSTOMER_ADVOCATE,
    GRAPH_EXECUTOR,
    GRAPH_INVESTIGATOR,
    GRAPH_POLICY_READER,
)
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

TICKET = "TCK-DEMO-01"
CEILING = Decimal("75.00")

# Signing key for the demo's approval tokens. Not a credential: it authenticates
# this process to itself. In deployment it comes from the environment and rotates.
APPROVAL_KEY = os.environ.get("BACKSTOP_DEMO_APPROVAL_KEY", "backstop-demo-key-16-plus")

ESC = "\033"
BOLD, GREEN, YELLOW, RED = "1", "32", "33", "31"

# Colour only when a person is watching. Piped to a file or a CI log, escape codes
# make the output harder to read, not easier.
COLOUR = sys.stdout.isatty()

PRINCIPAL_WIDTH = 32


def paint(code: str, text: str) -> str:
    return f"{ESC}[{code}m{text}{ESC}[0m" if COLOUR else text


def heading(text: str) -> None:
    print(f"\n{paint(BOLD, text)}")
    print("-" * len(text))


def line(label: str, value: object) -> None:
    print(f"  {label:<28} {value}")


def outcome(marker: str, colour: str, principal_id: str, tool: str, suffix: str = "") -> None:
    print(
        f"  {paint(colour, marker):<{len(marker) + (9 if COLOUR else 0)}} "
        f"{principal_id:<{PRINCIPAL_WIDTH}} {tool}{suffix}"
    )


async def call(gateway: ToolGateway, principal: Principal, tool: str, /, **args: Any) -> Any:
    result = await gateway.invoke(principal=principal, ticket_id=TICKET, tool=tool, args=args)
    outcome("ok  ", GREEN, principal.id, tool, " (replayed)" if result.replayed else "")
    return result.value


def pick_scenario() -> tuple[str, str]:
    """A customer who repeatedly reports parcels missing, and one of their orders.

    Chosen from the planted cohort so the demo exercises the interesting path: the
    carrier can evidence delivery, so policy refers the claim for review rather
    than settling it automatically.
    """
    suspects = [
        customer_id
        for annotation in dataset().fraud_annotations
        if annotation.pattern is FraudPattern.DELIVERY_CLAIM_ABUSE
        for customer_id in annotation.customer_ids
    ]
    customer_id = suspects[0]
    order = store().list_customer_orders(customer_id, limit=1)[0]
    return customer_id, order.id


async def main() -> int:
    customer_id, order_id = pick_scenario()

    gateway = ToolGateway(
        registry=DEFAULT_REGISTRY,
        handlers=await local_handlers(),
        approvals=(approvals := ApprovalAuthority(APPROVAL_KEY)),
        policy=StaticPolicy(ceiling=CEILING, kill_switch=False),
    )

    print(paint(BOLD, "Backstop - resolving one ticket through the tool plane"))
    line("ticket", TICKET)
    line("customer", customer_id)
    line("order", order_id)
    line("auto-approve ceiling", f"EUR {CEILING}")
    line("dataset reference date", store().reference_date.date().isoformat())

    # -- 1 -----------------------------------------------------------------
    heading("1. Gather facts")

    order = await call(gateway, GRAPH_INVESTIGATOR, "get_order", order_id=order_id)
    profile = await call(
        gateway, GRAPH_INVESTIGATOR, "get_customer_profile", customer_id=customer_id
    )
    tracking = await call(gateway, GRAPH_INVESTIGATOR, "track_shipment", order_id=order_id)

    print()
    line("order total", f"EUR {order['total']}")
    line("account age", f"{profile['tenure_days']} days")
    line("return rate", f"{profile['return_rate']:.0%}")
    line("prior non-receipt claims", profile["never_arrived_claims"])
    line("accounts at this address", profile["accounts_at_this_address"])
    line("delivery evidence", tracking["shipment"]["evidence_strength"])
    line("signature captured", tracking["shipment"]["signature_captured"])

    # -- 2 -----------------------------------------------------------------
    heading("2. Retrieve policy")

    found = await call(
        gateway,
        GRAPH_POLICY_READER,
        "search_policy",
        query="customer reports parcel never arrived but carrier recorded signature",
        limit=4,
    )
    print()
    for hit in found["results"]:
        print(f"  {hit['clause_id']:<8} {hit['score']:>6.2f}  {hit['text'][:70]}")

    # -- 3 -----------------------------------------------------------------
    heading("3. Attempt the refund")

    refund_args = {
        "order_id": order_id,
        "amount_eur": order["total"],
        "reason": "customer reports non-receipt",
    }

    try:
        await call(gateway, GRAPH_EXECUTOR, "issue_refund", **refund_args)
    except ApprovalRequired as refusal:
        outcome("hold", YELLOW, GRAPH_EXECUTOR.id, "issue_refund")
        print()
        line("refused because", refusal)
        line("amount", f"EUR {refusal.amount}")
        line("ceiling", f"EUR {refusal.ceiling}")
        print("\n  In the graph this is where interrupt() pauses the ticket and the")
        print("  approval lands in a human's queue. Here we grant it directly.")
    else:
        print("  refunded without approval - unexpected for an amount this size")
        return 1

    # -- 4 -----------------------------------------------------------------
    heading("4. A human approves, bound to these exact arguments")

    token = approvals.issue(
        ticket_id=TICKET,
        tool="issue_refund",
        args=refund_args,
        approver="ops.supervisor",
        max_amount=Decimal(order["total"]),
    )
    line("approver", token.approver)
    line("bound to arguments", token.args_digest[:16] + "...")
    line("expires", token.expires_at.isoformat(timespec="seconds"))
    print()

    granted = await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args=refund_args,
        approval=token,
    )
    outcome("ok  ", GREEN, GRAPH_EXECUTOR.id, "issue_refund")
    line("reference", granted.value["reference"])
    line("amount", f"EUR {granted.value['amount_eur']}")

    # -- 5 -----------------------------------------------------------------
    heading("5. The graph crashes and replays the same call")

    replay = await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args=refund_args,
        approval=token,
    )
    outcome("ok  ", GREEN, GRAPH_EXECUTOR.id, "issue_refund", " (replayed)")
    line("same reference", replay.value["reference"] == granted.value["reference"])

    movements = await call(gateway, GRAPH_EXECUTOR, "get_movements_for_order", order_id=order_id)
    line("movements on the order", len(movements["movements"]))
    line("total refunded", f"EUR {movements['total_refunded']}")
    if len(movements["movements"]) != 1:
        print("  the customer was refunded twice - idempotency is broken")
        return 1

    # -- 6 -----------------------------------------------------------------
    heading("6. What the deliberation room cannot do")

    try:
        await gateway.invoke(
            principal=DELIBERATION_CUSTOMER_ADVOCATE,
            ticket_id=TICKET,
            tool="issue_refund",
            args=refund_args,
        )
    except GatewayError as refusal:
        outcome("deny", RED, DELIBERATION_CUSTOMER_ADVOCATE.id, "issue_refund")
        line("refused because", refusal)
    else:
        print("  the advocate moved money - the capability boundary is broken")
        return 1

    # -- 7 -----------------------------------------------------------------
    heading("7. The audit chain")

    entries = gateway.audit.for_ticket(TICKET)
    print(f"  {'seq':<5}{'outcome':<11}{'principal':<{PRINCIPAL_WIDTH}}{'tool':<26}detail")
    for entry in entries:
        detail = entry.refusal_code or (f"{entry.duration_ms:.1f}ms" if entry.duration_ms else "")
        print(
            f"  {entry.sequence:<5}{entry.outcome.value:<11}"
            f"{entry.principal:<{PRINCIPAL_WIDTH}}{entry.tool:<26}{detail}"
        )

    gateway.audit.verify()
    print()
    line("entries", len(entries))
    line("chain verified", "yes")
    line("head", gateway.audit.head[:24] + "...")

    heading("8. Tampering with the record")

    # Reaching into the private list is the point: this simulates someone editing
    # the row out of band, which is the only way it could happen.
    tampered = entries[0].model_copy(update={"outcome": entries[-1].outcome})
    gateway.audit._entries[0] = tampered
    try:
        gateway.audit.verify()
    except ValueError as broken:
        line("verifier says", broken)
    else:
        print(f"  {paint(RED, 'the chain did not notice')}")
        return 1

    print()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32" and COLOUR:
        # Enables VT escape processing in the Windows console.
        os.system("")  # noqa: S605, S607 - no user input reaches this
    raise SystemExit(asyncio.run(main()))
