"""Read access to the domain records.

:class:`DomainStore` is the interface the MCP servers depend on. One
implementation ships today - :class:`MemoryStore`, built from a generated
:class:`~backstop_domain.generator.Dataset` and indexed on load. A Postgres-backed
implementation arrives in Phase 2, when the database becomes mandatory anyway for
graph checkpoints; see ``docs/adr/0005-file-backed-domain-store.md`` for why that
order was chosen.

The interface is deliberately narrow. Every method corresponds to something an
agent genuinely needs, and nothing offers arbitrary querying: a tool surface that
accepts free-form filters is a tool surface an injected instruction can steer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from backstop_domain.generator import RETURN_WINDOW_DAYS, Dataset
from backstop_domain.models import (
    Customer,
    Order,
    Product,
    ReturnRecord,
    Shipment,
)
from backstop_domain.views import (
    CustomerProfile,
    ReturnEligibility,
    ReturnHistoryEntry,
    build_customer_profile,
    build_return_eligibility,
)

#: Hard ceiling on any list-returning tool. An agent that asks for "all orders"
#: gets a bounded page, not a context-window flood.
MAX_PAGE_SIZE = 50


@runtime_checkable
class DomainStore(Protocol):
    """Read-only access to orders, customers, shipments, products and returns."""

    @property
    def reference_date(self) -> datetime:
        """The dataset's notion of now. All relative figures are computed from it."""
        ...

    def get_order(self, order_id: str) -> Order | None: ...

    def list_customer_orders(self, customer_id: str, *, limit: int = 20) -> list[Order]: ...

    def get_customer(self, customer_id: str) -> Customer | None: ...

    def get_customer_profile(self, customer_id: str) -> CustomerProfile | None: ...

    def get_shipment_for_order(self, order_id: str) -> Shipment | None: ...

    def get_shipment(self, shipment_id: str) -> Shipment | None: ...

    def get_product(self, sku: str) -> Product | None: ...

    def get_return_eligibility(self, order_id: str, sku: str) -> ReturnEligibility | None: ...

    def list_returns_for_customer(
        self, customer_id: str, *, limit: int = 20
    ) -> list[ReturnHistoryEntry]: ...


class MemoryStore:
    """In-memory store backed by a generated dataset.

    Indexes are built once on construction. With 2,000 orders the whole thing is
    a few megabytes, which keeps every test and every lab runnable without a
    database.
    """

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset
        self._reference_date = dataset.config.reference_date

        self._orders = {order.id: order for order in dataset.orders}
        self._customers = {customer.id: customer for customer in dataset.customers}
        self._products = {product.sku: product for product in dataset.products}
        self._shipments = {shipment.id: shipment for shipment in dataset.shipments}

        self._shipment_by_order: dict[str, Shipment] = {
            shipment.order_id: shipment for shipment in dataset.shipments
        }

        self._orders_by_customer: dict[str, list[Order]] = {}
        for order in dataset.orders:
            self._orders_by_customer.setdefault(order.customer_id, []).append(order)
        for order_list in self._orders_by_customer.values():
            order_list.sort(key=lambda order: order.placed_at, reverse=True)

        self._returns_by_customer: dict[str, list[ReturnRecord]] = {}
        for record in dataset.returns:
            self._returns_by_customer.setdefault(record.customer_id, []).append(record)
        for record_list in self._returns_by_customer.values():
            record_list.sort(key=lambda record: record.created_at, reverse=True)

        # Counting accounts per address is what makes the address-reuse signal
        # visible to a tool caller without exposing the fraud labels.
        self._accounts_per_address: dict[str, int] = {}
        for customer in dataset.customers:
            key = customer.address.fingerprint()
            self._accounts_per_address[key] = self._accounts_per_address.get(key, 0) + 1

        self._delivered_order_ids = {
            shipment.order_id for shipment in dataset.shipments if shipment.delivered_at
        }

    # -- identity ---------------------------------------------------------

    @property
    def reference_date(self) -> datetime:
        return self._reference_date

    @property
    def dataset(self) -> Dataset:
        """The underlying dataset. For the eval harness, never for a tool."""
        return self._dataset

    # -- orders -----------------------------------------------------------

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def list_customer_orders(self, customer_id: str, *, limit: int = 20) -> list[Order]:
        bounded = max(1, min(limit, MAX_PAGE_SIZE))
        return self._orders_by_customer.get(customer_id, [])[:bounded]

    # -- customers --------------------------------------------------------

    def get_customer(self, customer_id: str) -> Customer | None:
        return self._customers.get(customer_id)

    def get_customer_profile(self, customer_id: str) -> CustomerProfile | None:
        customer = self._customers.get(customer_id)
        if customer is None:
            return None

        return build_customer_profile(
            customer=customer,
            orders=self._orders_by_customer.get(customer_id, []),
            returns=self._returns_by_customer.get(customer_id, []),
            delivered_order_ids=self._delivered_order_ids,
            accounts_at_address=self._accounts_per_address.get(customer.address.fingerprint(), 1),
            reference_date=self._reference_date,
        )

    # -- shipments --------------------------------------------------------

    def get_shipment_for_order(self, order_id: str) -> Shipment | None:
        return self._shipment_by_order.get(order_id)

    def get_shipment(self, shipment_id: str) -> Shipment | None:
        return self._shipments.get(shipment_id)

    # -- catalogue --------------------------------------------------------

    def get_product(self, sku: str) -> Product | None:
        return self._products.get(sku)

    def get_return_eligibility(self, order_id: str, sku: str) -> ReturnEligibility | None:
        order = self._orders.get(order_id)
        product = self._products.get(sku)
        if order is None or product is None or order.line_for(sku) is None:
            return None

        return build_return_eligibility(
            product=product,
            order=order,
            shipment=self._shipment_by_order.get(order_id),
            window_days=RETURN_WINDOW_DAYS,
            reference_date=self._reference_date,
        )

    # -- returns ----------------------------------------------------------

    def list_returns_for_customer(
        self, customer_id: str, *, limit: int = 20
    ) -> list[ReturnHistoryEntry]:
        bounded = max(1, min(limit, MAX_PAGE_SIZE))
        entries: list[ReturnHistoryEntry] = []

        for record in self._returns_by_customer.get(customer_id, [])[:bounded]:
            shipment = self._shipment_by_order.get(record.order_id)
            delivered_at = shipment.delivered_at if shipment else None
            gap = (record.created_at - delivered_at).days if delivered_at else None

            entries.append(
                ReturnHistoryEntry(
                    return_id=record.id,
                    order_id=record.order_id,
                    sku=record.sku,
                    reason=record.reason,
                    resolution=record.resolution,
                    amount=record.amount,
                    created_at=record.created_at,
                    days_after_delivery=gap,
                )
            )

        return entries


__all__ = ["MAX_PAGE_SIZE", "DomainStore", "MemoryStore"]
