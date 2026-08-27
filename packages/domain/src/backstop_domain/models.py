"""Domain models for retail customer operations.

Two conventions run through this module.

**Money is ``Decimal``, never ``float``.** This system issues refunds. Binary
floating point is the wrong representation for money, and a portfolio project that
gets that wrong is not a portfolio project. Amounts are quantised to two decimal
places on construction so that a sum of line totals equals the stored order total
exactly.

**Identifiers are typed strings with a prefix.** ``ORD-0001234`` rather than a bare
integer. When an identifier turns up in a log line, an audit entry or a model's
reasoning, its type is obvious without a lookup - which matters a great deal when
you are reconstructing why an agent did something.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backstop_domain.money import Money, money
from backstop_domain.text import fingerprint

# ---------------------------------------------------------------------------
# Identifier types
# ---------------------------------------------------------------------------

CustomerId = Annotated[str, Field(pattern=r"^CUS-\d{5}$", examples=["CUS-00042"])]
OrderId = Annotated[str, Field(pattern=r"^ORD-\d{7}$", examples=["ORD-0001234"])]
ShipmentId = Annotated[str, Field(pattern=r"^SHP-\d{7}$", examples=["SHP-0001234"])]
ProductSku = Annotated[str, Field(pattern=r"^SKU-[A-Z]{3}-\d{4}$", examples=["SKU-APP-0117"])]
ReturnId = Annotated[str, Field(pattern=r"^RET-\d{6}$", examples=["RET-000512"])]
ClauseId = Annotated[str, Field(pattern=r"^[A-Z]{2}-\d+\.\d+$", examples=["RP-2.1", "DP-5.3"])]


class Frozen(BaseModel):
    """Base for records that are read-only once loaded."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CustomerTier(StrEnum):
    STANDARD = "standard"
    GOLD = "gold"
    PLATINUM = "platinum"


class ProductCategory(StrEnum):
    APPAREL = "apparel"
    HOME = "home"
    ELECTRONICS = "electronics"
    BEAUTY = "beauty"
    GROCERY = "grocery"


class OrderStatus(StrEnum):
    PLACED = "placed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class PaymentMethod(StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    CASH_ON_DELIVERY = "cash_on_delivery"
    STORE_CREDIT = "store_credit"


class ShipmentStatus(StrEnum):
    LABEL_CREATED = "label_created"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    LOST = "lost"
    RETURNED_TO_SENDER = "returned_to_sender"


class DeliveryEventCode(StrEnum):
    PICKED_UP = "picked_up"
    DEPARTED_HUB = "departed_hub"
    ARRIVED_HUB = "arrived_hub"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class ReturnReason(StrEnum):
    DAMAGED_ON_ARRIVAL = "damaged_on_arrival"
    WRONG_ITEM = "wrong_item"
    NEVER_ARRIVED = "never_arrived"
    NOT_AS_DESCRIBED = "not_as_described"
    CHANGED_MIND = "changed_mind"
    SIZE_ISSUE = "size_issue"
    LATE_DELIVERY = "late_delivery"


class Resolution(StrEnum):
    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    REPLACEMENT = "replacement"
    STORE_CREDIT = "store_credit"
    REJECTED = "rejected"


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


class Address(Frozen):
    line1: str
    city: str
    postal_code: str
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2")

    def fingerprint(self) -> str:
        """Normalised form used to spot several accounts sharing one address.

        Deliberately crude: Turkish-folded, punctuation dropped, joined on a
        separator so that an empty field cannot merge two different addresses.
        Real address matching is a specialism; this is enough to plant and detect
        the address-reuse pattern the evals depend on.
        """
        return fingerprint(self.line1, self.postal_code, self.country)


class Customer(Frozen):
    id: CustomerId
    name: str
    email: str
    phone: str
    tier: CustomerTier
    address: Address
    created_at: datetime
    marketing_opt_in: bool = False


class Product(Frozen):
    sku: ProductSku
    name: str
    category: ProductCategory
    price: Money
    weight_kg: float = Field(gt=0)

    # Eligibility flags. The policy documents refer to these by name, which keeps
    # retrieval honest: a clause about hygiene items can be checked against data
    # rather than inferred from a product title.
    final_sale: bool = False
    hygiene_sensitive: bool = False
    perishable: bool = False


class OrderLine(Frozen):
    sku: ProductSku
    quantity: int = Field(gt=0)
    unit_price: Money

    @property
    def line_total(self) -> Decimal:
        return money(self.unit_price * self.quantity)


class Order(Frozen):
    id: OrderId
    customer_id: CustomerId
    placed_at: datetime
    status: OrderStatus
    lines: tuple[OrderLine, ...] = Field(min_length=1)
    shipping_cost: Money
    payment_method: PaymentMethod
    delivery_address: Address
    currency: str = Field(default="EUR", min_length=3, max_length=3)

    @property
    def goods_total(self) -> Decimal:
        return money(sum((line.line_total for line in self.lines), Decimal(0)))

    @property
    def total(self) -> Decimal:
        return money(self.goods_total + self.shipping_cost)

    def line_for(self, sku: str) -> OrderLine | None:
        return next((line for line in self.lines if line.sku == sku), None)


class DeliveryEvent(Frozen):
    at: datetime
    code: DeliveryEventCode
    location: str
    description: str


class Shipment(Frozen):
    id: ShipmentId
    order_id: OrderId
    carrier: str
    tracking_number: str
    status: ShipmentStatus
    shipped_at: datetime | None
    delivered_at: datetime | None
    events: tuple[DeliveryEvent, ...] = ()

    # Evidence that matters when a customer says a parcel never arrived.
    signature_captured: bool = False
    delivery_photo: bool = False

    @model_validator(mode="after")
    def _delivered_shipments_have_a_delivery_time(self) -> Self:
        if self.status is ShipmentStatus.DELIVERED and self.delivered_at is None:
            raise ValueError("a delivered shipment must carry delivered_at")
        return self


class ReturnRecord(Frozen):
    id: ReturnId
    order_id: OrderId
    customer_id: CustomerId
    sku: ProductSku
    reason: ReturnReason
    resolution: Resolution
    status: ReturnStatus
    amount: Money
    created_at: datetime
    note: str = ""


__all__ = [
    "Address",
    "ClauseId",
    "Customer",
    "CustomerId",
    "CustomerTier",
    "DeliveryEvent",
    "DeliveryEventCode",
    "Frozen",
    "Order",
    "OrderId",
    "OrderLine",
    "OrderStatus",
    "PaymentMethod",
    "Product",
    "ProductCategory",
    "ProductSku",
    "Resolution",
    "ReturnId",
    "ReturnReason",
    "ReturnRecord",
    "ReturnStatus",
    "Shipment",
    "ShipmentId",
    "ShipmentStatus",
]
