"""Derived read models.

These are the shapes the MCP tools return. They are not stored; they are computed
from the records so that an agent receives *facts it can reason about* rather than
rows it would have to aggregate itself.

The distinction matters for two reasons.

**Reliability.** Asking a language model to compute a return rate from a list of
orders is asking it to do arithmetic under pressure. Computing it here makes the
number correct by construction.

**Auditability.** A derived field is deterministic and reproducible from the
underlying records, so a decision dossier can show both the input rows and the
figure the agent actually saw.

None of these views expose the fraud ground truth in :mod:`backstop_domain.fraud`.
They expose the *signals* an investigator would reasonably have - account age,
return rate, delivery evidence, accounts sharing an address - and leave the
judgement to the agent.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from backstop_domain.models import (
    Address,
    Customer,
    CustomerTier,
    Order,
    Product,
    ReturnReason,
    ReturnRecord,
    Shipment,
)
from backstop_domain.money import Money, money


class View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CustomerProfile(View):
    """Everything a resolution agent should know about a customer up front."""

    customer_id: str
    name: str
    email: str
    tier: CustomerTier
    address: Address
    created_at: datetime
    tenure_days: int = Field(ge=0, description="Account age at the reference date")

    total_orders: int = Field(ge=0)
    delivered_orders: int = Field(ge=0)
    total_returns: int = Field(ge=0)
    return_rate: float = Field(ge=0, le=1, description="Returns divided by delivered orders")
    lifetime_value: Money

    never_arrived_claims: int = Field(
        ge=0, description="Prior claims that a parcel was not received"
    )
    accounts_at_this_address: int = Field(
        ge=1, description="Customer accounts sharing this delivery address, including this one"
    )

    @property
    def is_new_account(self) -> bool:
        return self.tenure_days < 30


class ReturnHistoryEntry(View):
    """One prior return, trimmed to what a decision needs."""

    return_id: str
    order_id: str
    sku: str
    reason: ReturnReason
    resolution: str
    amount: Money
    created_at: datetime
    days_after_delivery: int | None = Field(
        default=None,
        description="Gap between delivery and the claim; None when delivery is unknown",
    )


class ReturnEligibility(View):
    """Whether an item can be returned at all, and why.

    Deliberately factual. It reports the window, the elapsed time and the product
    exclusions; it does **not** decide the outcome. The decision belongs to the
    policy engine and, above threshold, to a human.
    """

    sku: str
    order_id: str
    delivered_at: datetime | None
    days_since_delivery: int | None
    window_days: int
    within_window: bool

    final_sale: bool
    hygiene_sensitive: bool
    perishable: bool

    blocking_conditions: tuple[str, ...] = Field(
        default=(),
        description="Machine-readable reasons a standard return would not apply",
    )


class OrderSummary(View):
    """An order flattened for tool output."""

    order_id: str
    customer_id: str
    placed_at: datetime
    status: str
    currency: str
    goods_total: Money
    shipping_cost: Money
    total: Money
    line_count: int
    skus: tuple[str, ...]


def summarise_order(order: Order) -> OrderSummary:
    return OrderSummary(
        order_id=order.id,
        customer_id=order.customer_id,
        placed_at=order.placed_at,
        status=order.status,
        currency=order.currency,
        goods_total=order.goods_total,
        shipping_cost=order.shipping_cost,
        total=order.total,
        line_count=len(order.lines),
        skus=tuple(line.sku for line in order.lines),
    )


def build_customer_profile(
    *,
    customer: Customer,
    orders: list[Order],
    returns: list[ReturnRecord],
    delivered_order_ids: set[str],
    accounts_at_address: int,
    reference_date: datetime,
) -> CustomerProfile:
    delivered = [order for order in orders if order.id in delivered_order_ids]
    lifetime = money(sum((order.total for order in orders), Decimal(0)))

    # Denominator is delivered orders, not all orders: an order still in transit
    # has not had the chance to be returned, and counting it would make every
    # active buyer look more honest than they are.
    rate = len(returns) / len(delivered) if delivered else 0.0

    return CustomerProfile(
        customer_id=customer.id,
        name=customer.name,
        email=customer.email,
        tier=customer.tier,
        address=customer.address,
        created_at=customer.created_at,
        tenure_days=max((reference_date - customer.created_at).days, 0),
        total_orders=len(orders),
        delivered_orders=len(delivered),
        total_returns=len(returns),
        return_rate=min(round(rate, 4), 1.0),
        lifetime_value=lifetime,
        never_arrived_claims=sum(
            1 for record in returns if record.reason is ReturnReason.NEVER_ARRIVED
        ),
        accounts_at_this_address=accounts_at_address,
    )


def build_return_eligibility(
    *,
    product: Product,
    order: Order,
    shipment: Shipment | None,
    window_days: int,
    reference_date: datetime,
) -> ReturnEligibility:
    delivered_at = shipment.delivered_at if shipment else None
    days_since = (reference_date - delivered_at).days if delivered_at else None
    within = days_since is not None and days_since <= window_days

    blocking: list[str] = []
    if product.final_sale:
        blocking.append("final_sale_item")
    if product.hygiene_sensitive:
        blocking.append("hygiene_sensitive_item")
    if product.perishable:
        blocking.append("perishable_item")
    if delivered_at is None:
        blocking.append("not_yet_delivered")
    elif not within:
        blocking.append("outside_return_window")

    return ReturnEligibility(
        sku=product.sku,
        order_id=order.id,
        delivered_at=delivered_at,
        days_since_delivery=days_since,
        window_days=window_days,
        within_window=within,
        final_sale=product.final_sale,
        hygiene_sensitive=product.hygiene_sensitive,
        perishable=product.perishable,
        blocking_conditions=tuple(blocking),
    )


__all__ = [
    "CustomerProfile",
    "OrderSummary",
    "ReturnEligibility",
    "ReturnHistoryEntry",
    "View",
    "build_customer_profile",
    "build_return_eligibility",
    "summarise_order",
]
