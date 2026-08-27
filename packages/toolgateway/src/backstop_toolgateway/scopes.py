"""Capabilities: what exists, what it costs, and who may call it.

The registry is the single declaration of the tool surface. Nothing is callable
through the gateway unless it appears here, which means adding a capability is a
reviewable diff in one file rather than a decorator somewhere in a server module.

Read the ``payments`` entries and the design becomes obvious: writing is not a
property of a handler, it is a property declared here, enforced before the handler
is reached, and audited whether or not the handler runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Scope(StrEnum):
    """Coarse capability grants. A principal holds a set of these."""

    ORDERS_READ = "orders:read"
    SHIPPING_READ = "shipping:read"
    CATALOG_READ = "catalog:read"
    POLICY_READ = "policy:read"
    PAYMENTS_READ = "payments:read"
    PAYMENTS_WRITE = "payments:write"


#: Every read scope. The deliberation room gets exactly this and nothing more.
#:
#: ``payments:read`` belongs here: knowing whether an order has already been
#: refunded is a fact an investigator needs, and withholding it produces the
#: double-refund recommendation rather than preventing it. Reading movements is
#: not the capability that matters; writing them is.
READ_ONLY: frozenset[Scope] = frozenset(
    {
        Scope.ORDERS_READ,
        Scope.SHIPPING_READ,
        Scope.CATALOG_READ,
        Scope.POLICY_READ,
        Scope.PAYMENTS_READ,
    }
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """The declared contract of one tool."""

    name: str
    scope: Scope
    server: str
    summary: str

    #: Whether the tool changes state outside this process.
    write: bool = False

    #: Whether a signed human approval is required regardless of amount. Distinct
    #: from the amount ceiling below: some actions need a person even for a
    #: trivial sum, because the action is not reversible.
    always_requires_approval: bool = False

    #: Argument holding the monetary amount, when the tool moves money. The
    #: gateway reads it to apply the approval ceiling. ``None`` means the tool
    #: moves no money and the ceiling does not apply.
    amount_argument: str | None = None

    #: Whether repeating the call with the same arguments is safe. Every write
    #: tool here is idempotent *because the gateway makes it so*, by refusing to
    #: execute a second call bearing the same idempotency key.
    idempotent: bool = True

    #: Calls per minute per principal. A read tool called in a tight loop is
    #: usually a stuck agent rather than an attack, but both should be stopped.
    rate_limit_per_minute: int = 60

    @property
    def requires_approval_unconditionally(self) -> bool:
        return self.always_requires_approval

    @property
    def moves_money(self) -> bool:
        return self.amount_argument is not None


class ToolRegistry:
    """The declared tool surface."""

    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        duplicates = {spec.name for spec in specs if sum(s.name == spec.name for s in specs) > 1}
        if duplicates:
            raise ValueError(f"duplicate tool names in registry: {', '.join(sorted(duplicates))}")
        self._specs = {spec.name: spec for spec in specs}

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def for_scopes(self, scopes: frozenset[Scope]) -> tuple[ToolSpec, ...]:
        """Tools a principal holding ``scopes`` may call.

        Used to build the tool list advertised to a model. A model that is never
        told a tool exists is markedly harder to talk into calling it - defence in
        depth behind the hard check, not instead of it.
        """
        return tuple(
            spec
            for spec in sorted(self._specs.values(), key=lambda s: s.name)
            if spec.scope in scopes
        )

    def write_tools(self) -> tuple[ToolSpec, ...]:
        return tuple(
            spec for spec in sorted(self._specs.values(), key=lambda s: s.name) if spec.write
        )


#: The declared surface for retail customer operations.
DEFAULT_REGISTRY = ToolRegistry(
    (
        # -- orders ---------------------------------------------------------
        ToolSpec(
            name="get_order",
            scope=Scope.ORDERS_READ,
            server="orders",
            summary="Fetch one order by id, with its lines and totals.",
        ),
        ToolSpec(
            name="list_customer_orders",
            scope=Scope.ORDERS_READ,
            server="orders",
            summary="List a customer's recent orders, newest first.",
            rate_limit_per_minute=30,
        ),
        ToolSpec(
            name="list_customer_returns",
            scope=Scope.ORDERS_READ,
            server="orders",
            summary="A customer's prior returns, with the gap between delivery and claim.",
            rate_limit_per_minute=30,
        ),
        ToolSpec(
            name="get_customer_profile",
            scope=Scope.ORDERS_READ,
            server="orders",
            summary="Customer profile with tenure, return rate and claim history.",
            rate_limit_per_minute=30,
        ),
        # -- shipping -------------------------------------------------------
        ToolSpec(
            name="track_shipment",
            scope=Scope.SHIPPING_READ,
            server="shipping",
            summary="Shipment status and delivery evidence for an order.",
        ),
        ToolSpec(
            name="get_delivery_events",
            scope=Scope.SHIPPING_READ,
            server="shipping",
            summary="Full carrier event timeline for a shipment.",
        ),
        # -- catalogue ------------------------------------------------------
        ToolSpec(
            name="get_product",
            scope=Scope.CATALOG_READ,
            server="catalog",
            summary="Product details including return-exclusion flags.",
        ),
        ToolSpec(
            name="get_return_eligibility",
            scope=Scope.CATALOG_READ,
            server="catalog",
            summary="Whether an item is inside its return window, and what blocks it.",
        ),
        # -- policy ---------------------------------------------------------
        ToolSpec(
            name="search_policy",
            scope=Scope.POLICY_READ,
            server="policy",
            summary="Rank policy clauses against a text query.",
            rate_limit_per_minute=40,
        ),
        ToolSpec(
            name="get_policy_clause",
            scope=Scope.POLICY_READ,
            server="policy",
            summary="Fetch one clause verbatim by its id.",
        ),
        ToolSpec(
            name="get_policy_section",
            scope=Scope.POLICY_READ,
            server="policy",
            summary="Every clause in one section, in order.",
        ),
        ToolSpec(
            name="list_policy_documents",
            scope=Scope.POLICY_READ,
            server="policy",
            summary="Policy documents in force, with versions and effective dates.",
        ),
        # -- payments -------------------------------------------------------
        ToolSpec(
            name="get_movements_for_order",
            scope=Scope.PAYMENTS_READ,
            server="payments",
            summary="Refunds, credits and replacements already recorded on an order.",
        ),
        ToolSpec(
            name="issue_refund",
            scope=Scope.PAYMENTS_WRITE,
            server="payments",
            summary="Refund an amount to the original payment method.",
            write=True,
            amount_argument="amount_eur",
            rate_limit_per_minute=10,
        ),
        ToolSpec(
            name="issue_store_credit",
            scope=Scope.PAYMENTS_WRITE,
            server="payments",
            summary="Grant store credit to a customer account.",
            write=True,
            amount_argument="amount_eur",
            rate_limit_per_minute=10,
        ),
        ToolSpec(
            name="create_replacement_order",
            scope=Scope.PAYMENTS_WRITE,
            server="payments",
            summary="Dispatch a replacement for an item on an existing order.",
            write=True,
            # No amount to compare against a ceiling, and shipping goods is not
            # reversible by cancelling a transfer. A person decides, every time.
            always_requires_approval=True,
            rate_limit_per_minute=10,
        ),
    )
)

#: Fallback ceiling used when no governance setting is supplied. Kept low on
#: purpose: a misconfiguration should fail towards asking a human.
DEFAULT_AUTO_APPROVE_CEILING = Decimal("75.00")


__all__ = [
    "DEFAULT_AUTO_APPROVE_CEILING",
    "DEFAULT_REGISTRY",
    "READ_ONLY",
    "Scope",
    "ToolRegistry",
    "ToolSpec",
]
