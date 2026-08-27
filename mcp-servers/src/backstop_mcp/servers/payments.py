"""Payments MCP server. The one that moves money.

Read the layering here carefully, because it is the part most often got wrong.

**This server does not decide anything.** It performs no approval check, applies
no ceiling, and consults no policy. Authorisation happens at the tool gateway,
before this process is ever reached. Duplicating the checks here would feel safer
and would in fact be worse: two implementations of one rule drift, and the day
they disagree nobody knows which one is the policy.

**What it does do is refuse the impossible.** A negative amount, a refund larger
than the order, an unknown order - these are not authorisation questions, they are
integrity questions, and a service that moves money answers them itself rather
than trusting its caller. The gateway decides *whether* you may; this server
decides whether what you asked for is coherent.

The ledger is in-process, which is what a synthetic environment should have. The
shape of a real integration is the same: an idempotency key, an amount, a
reference, and a receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from backstop_domain.money import money
from backstop_mcp.context import NotFound, store

server = MCPServer(
    "backstop-payments",
    version="0.1.0",
    instructions=(
        "Refunds, store credit and replacements. WRITE. "
        "Authorisation is enforced by the tool gateway, not here."
    ),
)


class MovementKind(StrEnum):
    REFUND = "refund"
    STORE_CREDIT = "store_credit"
    REPLACEMENT = "replacement"


class PaymentRefused(ToolError):
    """The request is not coherent. Not an authorisation failure.

    A deliberate tool error, so the reason reaches the caller: an agent told only
    that the call "failed" will retry it, whereas one told the refund would exceed
    the order total can correct the amount. Contrast the gateway, which withholds
    upstream failure detail - there the caller has nothing useful to do with it.
    """


@dataclass(frozen=True, slots=True)
class Movement:
    reference: str
    kind: MovementKind
    order_id: str
    customer_id: str
    amount: Decimal
    at: datetime
    reason: str


@dataclass(slots=True)
class Ledger:
    """In-process record of everything this server has done."""

    movements: list[Movement] = field(default_factory=list)

    def next_reference(self, kind: MovementKind) -> str:
        prefix = {"refund": "REF", "store_credit": "CRD", "replacement": "RPL"}[kind.value]
        return f"{prefix}-{len(self.movements) + 1:06d}"

    def record(self, movement: Movement) -> Movement:
        self.movements.append(movement)
        return movement

    def total_refunded(self, order_id: str) -> Decimal:
        return money(
            sum(
                (
                    movement.amount
                    for movement in self.movements
                    if movement.order_id == order_id and movement.kind is MovementKind.REFUND
                ),
                Decimal(0),
            )
        )


ledger = Ledger()


def _parse_amount(raw: str | float | int) -> Decimal:
    try:
        amount = money(raw)
    except (ValueError, InvalidOperation) as exc:
        raise PaymentRefused(f"{raw!r} is not a valid amount") from exc
    if amount <= 0:
        raise PaymentRefused("amount must be greater than zero")
    return amount


@server.tool()
def issue_refund(order_id: str, amount_eur: str, reason: str) -> dict[str, Any]:
    """Refund an amount against an order, to the original payment method.

    Authorisation is the gateway's responsibility. This tool verifies only that
    the request is coherent: the order exists, the amount is positive, and the
    total refunded does not exceed what was paid.

    Args:
        order_id: Order to refund against.
        amount_eur: Amount in EUR, as a decimal string, for example "49.90".
        reason: Short justification, recorded on the movement.
    """
    order = store().get_order(order_id)
    if order is None:
        raise NotFound(f"no order with id {order_id}")

    amount = _parse_amount(amount_eur)

    # Over-refunding is the integrity failure this server exists to prevent. It
    # also catches a specific agent error: refunding the order total once per
    # line, which looks entirely reasonable one call at a time.
    already = ledger.total_refunded(order_id)
    if already + amount > order.total:
        raise PaymentRefused(
            f"refunding {amount} would exceed the order total of {order.total} "
            f"({already} already refunded)"
        )

    movement = ledger.record(
        Movement(
            reference=ledger.next_reference(MovementKind.REFUND),
            kind=MovementKind.REFUND,
            order_id=order_id,
            customer_id=order.customer_id,
            amount=amount,
            at=datetime.now(UTC),
            reason=reason,
        )
    )

    return {
        "reference": movement.reference,
        "kind": movement.kind.value,
        "order_id": order_id,
        "customer_id": order.customer_id,
        "amount_eur": str(amount),
        "payment_method": order.payment_method.value,
        "order_total": str(order.total),
        "total_refunded_on_order": str(ledger.total_refunded(order_id)),
        "at": movement.at.isoformat(),
    }


@server.tool()
def issue_store_credit(customer_id: str, amount_eur: str, reason: str) -> dict[str, Any]:
    """Grant store credit to a customer account.

    Args:
        customer_id: Customer to credit.
        amount_eur: Amount in EUR, as a decimal string.
        reason: Short justification, recorded on the movement.
    """
    customer = store().get_customer(customer_id)
    if customer is None:
        raise NotFound(f"no customer with id {customer_id}")

    amount = _parse_amount(amount_eur)

    movement = ledger.record(
        Movement(
            reference=ledger.next_reference(MovementKind.STORE_CREDIT),
            kind=MovementKind.STORE_CREDIT,
            order_id="",
            customer_id=customer_id,
            amount=amount,
            at=datetime.now(UTC),
            reason=reason,
        )
    )

    return {
        "reference": movement.reference,
        "kind": movement.kind.value,
        "customer_id": customer_id,
        "amount_eur": str(amount),
        "at": movement.at.isoformat(),
    }


@server.tool()
def create_replacement_order(order_id: str, sku: str, reason: str) -> dict[str, Any]:
    """Dispatch a replacement for one item on an existing order.

    Args:
        order_id: The original order.
        sku: The item to replace. Must appear on that order.
        reason: Short justification, recorded on the movement.
    """
    order = store().get_order(order_id)
    if order is None:
        raise NotFound(f"no order with id {order_id}")

    line = order.line_for(sku)
    if line is None:
        raise PaymentRefused(f"order {order_id} has no line for sku {sku}")

    movement = ledger.record(
        Movement(
            reference=ledger.next_reference(MovementKind.REPLACEMENT),
            kind=MovementKind.REPLACEMENT,
            order_id=order_id,
            customer_id=order.customer_id,
            amount=money(line.line_total),
            at=datetime.now(UTC),
            reason=reason,
        )
    )

    return {
        "reference": movement.reference,
        "kind": movement.kind.value,
        "order_id": order_id,
        "customer_id": order.customer_id,
        "sku": sku,
        "quantity": line.quantity,
        "goods_value": str(line.line_total),
        "at": movement.at.isoformat(),
    }


@server.tool()
def get_movements_for_order(order_id: str) -> dict[str, Any]:
    """Every movement recorded against an order.

    Present so that a decision dossier can show what actually happened, and so a
    replay can be recognised for what it is.

    Args:
        order_id: Order identifier.
    """
    movements = [item for item in ledger.movements if item.order_id == order_id]
    return {
        "order_id": order_id,
        "total_refunded": str(ledger.total_refunded(order_id)),
        "movements": [
            {
                "reference": item.reference,
                "kind": item.kind.value,
                "amount_eur": str(item.amount),
                "reason": item.reason,
                "at": item.at.isoformat(),
            }
            for item in movements
        ],
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
