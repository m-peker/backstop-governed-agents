"""Domain model, money, text folding and the synthetic dataset."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backstop_domain.generator import (
    RETURN_WINDOW_DAYS,
    GeneratorConfig,
    generate,
)
from backstop_domain.models import (
    Address,
    Order,
    OrderLine,
    OrderStatus,
    PaymentMethod,
    Shipment,
    ShipmentStatus,
)
from backstop_domain.money import money
from backstop_domain.store import MAX_PAGE_SIZE, MemoryStore
from backstop_domain.text import fingerprint, fold, slug

# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def test_float_input_does_not_bring_binary_error_with_it() -> None:
    assert money(0.1) + money(0.2) == Decimal("0.30")


def test_amounts_are_quantised_to_two_places() -> None:
    assert money("10") == Decimal("10.00")
    assert money(Decimal("3.14159")) == Decimal("3.14")


def test_half_rounds_up_the_way_a_customer_expects() -> None:
    assert money("0.125") == Decimal("0.13")
    assert money("1.005") == Decimal("1.01")


def test_a_non_amount_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a monetary amount"):
        money("about twenty euro")


def test_infinity_is_not_an_amount() -> None:
    with pytest.raises(ValueError, match="finite"):
        money(Decimal("Infinity"))


# ---------------------------------------------------------------------------
# Turkish text folding
# ---------------------------------------------------------------------------


def test_dotted_capital_i_folds_to_a_plain_i() -> None:
    """Python's default lower() leaves a combining dot behind."""
    assert "̇" in "İstanbul".lower()
    assert fold("İstanbul") == "istanbul"


def test_dotless_and_dotted_i_compare_equal() -> None:
    assert fold("Işık") == fold("isik")


def test_slug_strips_everything_but_alphanumerics() -> None:
    assert slug("Ayşe Öztürk-Yılmaz") == "ayseozturkyilmaz"


def test_fingerprint_keeps_fields_apart() -> None:
    """Without a separator, ("ab", "c") and ("a", "bc") would collide."""
    assert fingerprint("ab", "c") != fingerprint("a", "bc")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_order_total_is_the_sum_of_its_lines_plus_shipping() -> None:
    address = Address(line1="Lale Caddesi No:1", city="Bursa", postal_code="16100", country="TR")
    order = Order(
        id="ORD-0000001",
        customer_id="CUS-00001",
        placed_at=datetime(2026, 7, 1, tzinfo=UTC),
        status=OrderStatus.DELIVERED,
        lines=(
            OrderLine(sku="SKU-APP-0001", quantity=3, unit_price="19.99"),
            OrderLine(sku="SKU-HOM-0002", quantity=1, unit_price="5.01"),
        ),
        shipping_cost="4.99",
        payment_method=PaymentMethod.CARD,
        delivery_address=address,
    )

    # 19.99 x 3 = 59.97, plus 5.01 = 64.98, plus 4.99 shipping = 69.97
    assert order.goods_total == Decimal("64.98")
    assert order.total == Decimal("69.97")


def test_a_malformed_identifier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderLine(sku="not-a-sku", quantity=1, unit_price="1.00")


def test_a_delivered_shipment_must_say_when() -> None:
    with pytest.raises(ValidationError, match="delivered_at"):
        Shipment(
            id="SHP-0000001",
            order_id="ORD-0000001",
            carrier="Anadolu Kargo",
            tracking_number="AK000000001TR",
            status=ShipmentStatus.DELIVERED,
            shipped_at=datetime(2026, 7, 1, tzinfo=UTC),
            delivered_at=None,
        )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small() -> GeneratorConfig:
    return GeneratorConfig(customers=80, orders=300, products=40)


def test_the_same_seed_produces_the_same_world(small: GeneratorConfig) -> None:
    first = generate(small)
    second = generate(small)

    assert [order.id for order in first.orders] == [order.id for order in second.orders]
    assert [order.total for order in first.orders] == [order.total for order in second.orders]
    assert first.fraud_annotations == second.fraud_annotations


def test_a_different_seed_produces_a_different_world(small: GeneratorConfig) -> None:
    from dataclasses import replace

    other = generate(replace(small, seed=small.seed + 1))
    assert [order.total for order in generate(small).orders] != [
        order.total for order in other.orders
    ]


def test_the_requested_volumes_are_produced(small: GeneratorConfig) -> None:
    data = generate(small)

    assert len(data.customers) == small.customers
    assert len(data.products) == small.products
    # Cohort orders are allocated first, so the total can exceed the request but
    # must never fall short of it.
    assert len(data.orders) >= small.orders


def test_every_order_belongs_to_a_real_customer(small: GeneratorConfig) -> None:
    data = generate(small)
    known = {customer.id for customer in data.customers}

    assert all(order.customer_id in known for order in data.orders)


def test_every_order_line_references_a_real_product(small: GeneratorConfig) -> None:
    data = generate(small)
    known = {product.sku for product in data.products}

    assert all(line.sku in known for order in data.orders for line in order.lines)


def test_no_order_precedes_its_customers_registration(small: GeneratorConfig) -> None:
    data = generate(small)
    created = {customer.id: customer.created_at for customer in data.customers}

    assert all(order.placed_at >= created[order.customer_id] for order in data.orders)


def test_shipments_exist_only_for_dispatched_orders(small: GeneratorConfig) -> None:
    data = generate(small)
    by_id = {order.id: order for order in data.orders}

    for shipment in data.shipments:
        assert by_id[shipment.order_id].status is not OrderStatus.CANCELLED


def test_delivery_never_precedes_dispatch(small: GeneratorConfig) -> None:
    data = generate(small)

    for shipment in data.shipments:
        if shipment.delivered_at and shipment.shipped_at:
            assert shipment.delivered_at > shipment.shipped_at


def test_returns_follow_delivery(small: GeneratorConfig) -> None:
    data = generate(small)
    delivered = {
        shipment.order_id: shipment.delivered_at
        for shipment in data.shipments
        if shipment.delivered_at
    }

    for record in data.returns:
        assert record.order_id in delivered
        assert record.created_at >= delivered[record.order_id]


def test_each_customer_carries_at_most_one_planted_pattern(small: GeneratorConfig) -> None:
    """Overlapping patterns would make an eval label ambiguous."""
    data = generate(small)
    seen: set[str] = set()

    for annotation in data.fraud_annotations:
        for customer_id in annotation.customer_ids:
            assert customer_id not in seen, f"{customer_id} carries two patterns"
            seen.add(customer_id)


def test_wardrobing_returns_land_inside_the_stated_window(small: GeneratorConfig) -> None:
    """The pattern is "just inside the window", so it must be inside it."""
    from backstop_domain.fraud import FraudPattern

    data = generate(small)
    store = MemoryStore(data)
    wardrobers = {
        customer_id
        for annotation in data.fraud_annotations
        if annotation.pattern is FraudPattern.WARDROBING
        for customer_id in annotation.customer_ids
    }

    gaps = [
        entry.days_after_delivery
        for customer_id in wardrobers
        for entry in store.list_returns_for_customer(customer_id, limit=MAX_PAGE_SIZE)
        if entry.days_after_delivery is not None
    ]

    assert gaps, "wardrobers produced no returns"
    assert max(gaps) < RETURN_WINDOW_DAYS


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store(small: GeneratorConfig) -> MemoryStore:
    return MemoryStore(generate(small))


def test_unknown_identifiers_return_none(store: MemoryStore) -> None:
    assert store.get_order("ORD-9999999") is None
    assert store.get_customer("CUS-99999") is None
    assert store.get_product("SKU-ZZZ-9999") is None


def test_a_page_is_bounded_however_much_is_asked_for(store: MemoryStore) -> None:
    customer_id = store.dataset.customers[0].id
    assert len(store.list_customer_orders(customer_id, limit=10_000)) <= MAX_PAGE_SIZE


def test_return_rate_uses_delivered_orders_as_its_denominator(store: MemoryStore) -> None:
    """Counting orders still in transit would flatter every active buyer."""
    for customer in store.dataset.customers[:40]:
        profile = store.get_customer_profile(customer.id)
        assert profile is not None
        if profile.delivered_orders:
            assert profile.return_rate == pytest.approx(
                min(profile.total_returns / profile.delivered_orders, 1.0), abs=1e-4
            )
        else:
            assert profile.return_rate == 0.0


def test_eligibility_requires_the_sku_to_be_on_the_order(store: MemoryStore) -> None:
    order = store.dataset.orders[0]
    assert store.get_return_eligibility(order.id, "SKU-ZZZ-9999") is None


def test_a_final_sale_item_reports_that_as_a_blocking_condition(store: MemoryStore) -> None:
    final_sale = {product.sku for product in store.dataset.products if product.final_sale}
    assert final_sale, "the catalogue has no final-sale items to test with"

    for order in store.dataset.orders:
        for line in order.lines:
            if line.sku in final_sale:
                eligibility = store.get_return_eligibility(order.id, line.sku)
                assert eligibility is not None
                assert "final_sale_item" in eligibility.blocking_conditions
                return

    pytest.skip("no order in this sample contains a final-sale item")
