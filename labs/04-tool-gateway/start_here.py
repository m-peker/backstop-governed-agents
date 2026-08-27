"""Lab 04 - the tool gateway.

Run this as it stands and watch the customer get refunded twice.

Then fill in the four checks marked TODO and run ``check.py`` until it passes.
Every helper you need already exists in ``backstop_toolgateway``; the exercise is
deciding what to call and, more importantly, in what order.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from backstop_toolgateway.canonical import digest
from backstop_toolgateway.principal import GRAPH_EXECUTOR, Principal
from backstop_toolgateway.scopes import DEFAULT_REGISTRY, ToolRegistry

CEILING = Decimal("75.00")


class PaymentsLedger:
    """Stands in for the payments service, and counts how often it was hit."""

    def __init__(self) -> None:
        self.movements: list[dict[str, Any]] = []

    def refund(self, order_id: str, amount: str) -> dict[str, Any]:
        self.movements.append({"order_id": order_id, "amount": amount})
        return {"reference": f"REF-{len(self.movements):04d}", "amount_eur": amount}


class NaiveGateway:
    """No scope check, no idempotency, no approval, no audit.

    It calls the handler. That is all it does, and it is why the demo below pays
    the same customer twice.
    """

    def __init__(self, registry: ToolRegistry, ledger: PaymentsLedger) -> None:
        self._registry = registry
        self._ledger = ledger

    async def invoke(
        self, *, principal: Principal, ticket_id: str, tool: str, args: dict[str, Any]
    ) -> Any:
        spec = self._registry.get(tool)
        if spec is None:
            raise ValueError(f"no tool named {tool!r}")

        # TODO 1 - scope.
        #   Refuse before invoking when the principal does not hold spec.scope.
        #   Raise ScopeDenied from backstop_toolgateway.errors.

        # TODO 2 - idempotency.
        #   For a write tool, derive a key with
        #   backstop_toolgateway.idempotency.idempotency_key and return a stored
        #   result rather than calling the handler again.

        # TODO 3 - approval.
        #   When spec.amount_argument names an amount above CEILING, require a
        #   signed token. See backstop_toolgateway.approval.ApprovalAuthority, and
        #   note what the token is bound to - binding to the argument digest is
        #   the part that matters.

        result = self._ledger.refund(args["order_id"], args["amount_eur"])

        # TODO 4 - audit.
        #   Append an entry for every attempt, refusals included. Expose the
        #   chain as `self.audit` so the check can find it.
        #   See backstop_toolgateway.audit.AuditChain.

        return result


async def main() -> None:
    ledger = PaymentsLedger()
    gateway = NaiveGateway(DEFAULT_REGISTRY, ledger)

    args = {"order_id": "ORD-0000028", "amount_eur": "40.00", "reason": "damaged"}
    print(f"the idempotency key would be: {digest(args)[:16]}...\n")

    first = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id="TCK-LAB", tool="issue_refund", args=args
    )
    print("first call  ->", first)

    print("\n...the process crashes here, before the result was recorded...\n")

    replay = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id="TCK-LAB", tool="issue_refund", args=args
    )
    print("replay      ->", replay)

    print(f"\nmovements on the order: {len(ledger.movements)}")
    if len(ledger.movements) > 1:
        print("The customer was refunded twice, and nothing errored.")


if __name__ == "__main__":
    asyncio.run(main())
