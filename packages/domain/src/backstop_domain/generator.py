"""Deterministic synthetic dataset.

Everything is derived from a single seeded ``random.Random``. The same seed and
the same configuration always produce byte-identical output, which is what makes
evaluation scores comparable across runs and across machines.

The people in this dataset are not real. Names are drawn from common Turkish given
and family names and recombined at random; addresses, phone numbers and email
addresses are synthetic, with emails on the reserved ``example.com`` domain. The
dataset is shaped like the customer base of a Turkish retailer because that is the
domain the whole system models, and because it gives the PII lab genuine Turkish
identifiers to work with rather than an anglophone stand-in.

A small cohort of customers is given deliberate return-abuse behaviour. See
:mod:`backstop_domain.fraud` for what each pattern looks like and why it is
detectable from tool output alone.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backstop_domain import ids
from backstop_domain.fraud import FraudAnnotation, FraudPattern
from backstop_domain.models import (
    Address,
    Customer,
    CustomerTier,
    DeliveryEvent,
    DeliveryEventCode,
    Order,
    OrderLine,
    OrderStatus,
    PaymentMethod,
    Product,
    ProductCategory,
    Resolution,
    ReturnReason,
    ReturnRecord,
    ReturnStatus,
    Shipment,
    ShipmentStatus,
)
from backstop_domain.money import money
from backstop_domain.text import slug

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SEED = 20260825
#: The dataset's "today". Every relative date is computed from this so that the
#: data does not silently change meaning as the wall clock moves.
DEFAULT_REFERENCE_DATE = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

#: Standard return window in days. The policy documents state the same number;
#: `tests/test_policy_alignment.py` asserts the two never drift apart.
RETURN_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    seed: int = DEFAULT_SEED
    reference_date: datetime = DEFAULT_REFERENCE_DATE
    customers: int = 500
    orders: int = 2000
    products: int = 120

    #: Share of ordinary (non-cohort) delivered orders that end in a return.
    baseline_return_rate: float = 0.08

    serial_refunders: int = 6
    wardrobers: int = 5
    address_rings: int = 2
    address_ring_size: int = 3
    delivery_claim_abusers: int = 5
    high_value_newcomers: int = 4


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_GIVEN_NAMES = (
    "Ayşe",
    "Mehmet",
    "Fatma",
    "Mustafa",
    "Emine",
    "Ahmet",
    "Hatice",
    "Ali",
    "Zeynep",
    "Hüseyin",
    "Elif",
    "Hasan",
    "Meryem",
    "İbrahim",
    "Şerife",
    "Osman",
    "Zehra",
    "Yusuf",
    "Sultan",
    "Murat",
    "Hanife",
    "Ömer",
    "Havva",
    "Ramazan",
    "Merve",
    "Kemal",
    "Esra",
    "Serkan",
    "Büşra",
    "Burak",
    "Derya",
    "Emre",
    "Selin",
    "Tolga",
    "Nazlı",
    "Kaan",
    "Pınar",
    "Onur",
    "Gamze",
    "Barış",
)

_FAMILY_NAMES = (
    "Yılmaz",
    "Kaya",
    "Demir",
    "Şahin",
    "Çelik",
    "Yıldız",
    "Yıldırım",
    "Öztürk",
    "Aydın",
    "Özdemir",
    "Arslan",
    "Doğan",
    "Kılıç",
    "Aslan",
    "Çetin",
    "Kara",
    "Koç",
    "Kurt",
    "Özkan",
    "Şimşek",
    "Polat",
    "Korkmaz",
    "Bulut",
    "Erdoğan",
    "Aksoy",
    "Taş",
    "Güneş",
    "Bozkurt",
    "Ateş",
    "Karaca",
)

_CITIES = (
    ("Bursa", "16"),
    ("İstanbul", "34"),
    ("İzmir", "35"),
    ("Ankara", "06"),
    ("Antalya", "07"),
    ("Eskişehir", "26"),
    ("Denizli", "20"),
    ("Gaziantep", "27"),
    ("Konya", "42"),
    ("Adana", "01"),
    ("Trabzon", "61"),
    ("Kayseri", "38"),
)

_STREETS = (
    "Atatürk Caddesi",
    "İnönü Sokak",
    "Cumhuriyet Bulvarı",
    "Gazi Caddesi",
    "Fevzi Çakmak Sokak",
    "Barbaros Bulvarı",
    "Zafer Caddesi",
    "Menekşe Sokak",
    "Çınar Sokak",
    "Lale Caddesi",
    "Papatya Sokak",
    "Yeşilyurt Caddesi",
)

_CARRIERS = ("Anadolu Kargo", "Marmara Express", "Ege Lojistik", "Yurtiçi Hat")

_PRODUCT_NAMES: dict[ProductCategory, tuple[str, ...]] = {
    ProductCategory.APPAREL: (
        "Merino Wool Coat",
        "Linen Shirt",
        "Cotton Chinos",
        "Cashmere Scarf",
        "Quilted Jacket",
        "Knit Cardigan",
        "Denim Jacket",
        "Wool Blazer",
        "Silk Blouse",
        "Leather Belt",
        "Running Jacket",
        "Pleated Skirt",
    ),
    ProductCategory.HOME: (
        "Percale Duvet Set",
        "Turkish Cotton Towel",
        "Ceramic Dinner Set",
        "Wool Kilim Rug",
        "Linen Curtain Panel",
        "Cast Iron Pan",
        "Bamboo Bath Mat",
        "Glass Storage Jars",
        "Velvet Cushion Cover",
        "Copper Coffee Pot",
    ),
    ProductCategory.ELECTRONICS: (
        "Noise Cancelling Headphones",
        "Espresso Machine",
        "Robot Vacuum",
        "Air Purifier",
        "Smart Kettle",
        "Bluetooth Speaker",
        "Steam Iron",
        "Stand Mixer",
        "Electric Toothbrush",
        "Portable Projector",
    ),
    ProductCategory.BEAUTY: (
        "Argan Hair Oil",
        "Rose Water Toner",
        "Vitamin C Serum",
        "Clay Face Mask",
        "Shea Body Butter",
        "Sandalwood Eau de Parfum",
        "Bath Salt Set",
        "Lip Balm Trio",
    ),
    ProductCategory.GROCERY: (
        "Antep Pistachios",
        "Blossom Honey",
        "Olive Oil 1L",
        "Turkish Delight Box",
        "Dried Apricots",
        "Ground Coffee 250g",
        "Herbal Tea Selection",
        "Tahini Jar",
    ),
}

_PRICE_BANDS: dict[ProductCategory, tuple[int, int]] = {
    ProductCategory.APPAREL: (35, 480),
    ProductCategory.HOME: (20, 390),
    ProductCategory.ELECTRONICS: (45, 950),
    ProductCategory.BEAUTY: (12, 140),
    ProductCategory.GROCERY: (6, 60),
}

# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Cohorts:
    """Which customers were assigned which planted behaviour."""

    serial_refunders: set[str] = field(default_factory=set)
    wardrobers: set[str] = field(default_factory=set)
    address_rings: list[tuple[str, ...]] = field(default_factory=list)
    delivery_claim_abusers: set[str] = field(default_factory=set)
    high_value_newcomers: set[str] = field(default_factory=set)

    @property
    def ring_members(self) -> set[str]:
        return {member for ring in self.address_rings for member in ring}

    def all_flagged(self) -> set[str]:
        return (
            self.serial_refunders
            | self.wardrobers
            | self.ring_members
            | self.delivery_claim_abusers
            | self.high_value_newcomers
        )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dataset:
    """One generated world, plus the ground truth for its planted patterns."""

    config: GeneratorConfig
    products: tuple[Product, ...]
    customers: tuple[Customer, ...]
    orders: tuple[Order, ...]
    shipments: tuple[Shipment, ...]
    returns: tuple[ReturnRecord, ...]
    fraud_annotations: tuple[FraudAnnotation, ...]

    def summary(self) -> dict[str, int]:
        return {
            "products": len(self.products),
            "customers": len(self.customers),
            "orders": len(self.orders),
            "shipments": len(self.shipments),
            "returns": len(self.returns),
            "fraud_annotations": len(self.fraud_annotations),
        }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate(config: GeneratorConfig | None = None) -> Dataset:
    """Build the dataset. Pure and deterministic given ``config``."""
    config = config or GeneratorConfig()
    rng = random.Random(config.seed)  # noqa: S311 - synthetic data, not cryptography

    products = _build_products(rng, config)
    customers, cohorts = _build_customers(rng, config)
    orders = _build_orders(rng, config, customers, products, cohorts)
    shipments = _build_shipments(rng, config, orders, cohorts)
    returns = _build_returns(rng, config, customers, products, orders, shipments, cohorts)
    annotations = _build_annotations(cohorts, orders)

    return Dataset(
        config=config,
        products=products,
        customers=customers,
        orders=orders,
        shipments=shipments,
        returns=returns,
        fraud_annotations=annotations,
    )


def _build_products(rng: random.Random, config: GeneratorConfig) -> tuple[Product, ...]:
    products: list[Product] = []
    index = 0

    while len(products) < config.products:
        for category, names in _PRODUCT_NAMES.items():
            if len(products) >= config.products:
                break
            index += 1
            base_name = names[index % len(names)]
            low, high = _PRICE_BANDS[category]
            price = money(Decimal(rng.randint(low * 100, high * 100)) / 100)

            products.append(
                Product(
                    sku=ids.product_sku(category, index),
                    name=f"{base_name} {index:03d}" if index > len(names) else base_name,
                    category=category,
                    price=price,
                    weight_kg=round(rng.uniform(0.05, 12.0), 2),
                    final_sale=rng.random() < 0.08,
                    hygiene_sensitive=category is ProductCategory.BEAUTY,
                    perishable=category is ProductCategory.GROCERY,
                )
            )

    return tuple(products)


def _random_address(rng: random.Random) -> Address:
    city, plate = rng.choice(_CITIES)
    return Address(
        line1=f"{rng.choice(_STREETS)} No:{rng.randint(1, 240)}/{rng.randint(1, 30)}",
        city=city,
        postal_code=f"{plate}{rng.randint(100, 999):03d}",
        country="TR",
    )


def _build_customers(
    rng: random.Random, config: GeneratorConfig
) -> tuple[tuple[Customer, ...], _Cohorts]:
    customers: list[Customer] = []

    for index in range(1, config.customers + 1):
        given = rng.choice(_GIVEN_NAMES)
        family = rng.choice(_FAMILY_NAMES)
        tier = _weighted_tier(rng)
        age_days = rng.randint(3, 1200)

        customers.append(
            Customer(
                id=ids.customer_id(index),
                name=f"{given} {family}",
                email=f"{slug(given)}.{slug(family)}{index}@example.com",
                phone=f"+90 5{rng.randint(30, 59)} {rng.randint(100, 999)} "
                f"{rng.randint(10, 99)} {rng.randint(10, 99)}",
                tier=tier,
                address=_random_address(rng),
                created_at=config.reference_date - timedelta(days=age_days),
                marketing_opt_in=rng.random() < 0.4,
            )
        )

    cohorts = _assign_cohorts(rng, config, customers)
    customers = _apply_address_rings(customers, cohorts)
    customers = _apply_newcomer_ages(config, customers, cohorts)
    return tuple(customers), cohorts


def _weighted_tier(rng: random.Random) -> CustomerTier:
    roll = rng.random()
    if roll < 0.70:
        return CustomerTier.STANDARD
    if roll < 0.93:
        return CustomerTier.GOLD
    return CustomerTier.PLATINUM


def _assign_cohorts(
    rng: random.Random, config: GeneratorConfig, customers: list[Customer]
) -> _Cohorts:
    """Pick cohort members without overlap.

    Overlapping patterns would make an eval label ambiguous - a customer who is
    both a serial refunder and a wardrober gives partial credit for the wrong
    reason - so each customer carries at most one planted behaviour.
    """
    pool = [customer.id for customer in customers]
    rng.shuffle(pool)
    cursor = 0

    def take(count: int) -> list[str]:
        nonlocal cursor
        chunk = pool[cursor : cursor + count]
        cursor += count
        return chunk

    cohorts = _Cohorts()
    cohorts.serial_refunders = set(take(config.serial_refunders))
    cohorts.wardrobers = set(take(config.wardrobers))
    cohorts.address_rings = [
        tuple(take(config.address_ring_size)) for _ in range(config.address_rings)
    ]
    cohorts.delivery_claim_abusers = set(take(config.delivery_claim_abusers))
    cohorts.high_value_newcomers = set(take(config.high_value_newcomers))
    return cohorts


def _apply_address_rings(customers: list[Customer], cohorts: _Cohorts) -> list[Customer]:
    """Give every member of a ring the same delivery address."""
    by_id = {customer.id: customer for customer in customers}

    for ring in cohorts.address_rings:
        shared = by_id[ring[0]].address
        for member_id in ring[1:]:
            by_id[member_id] = by_id[member_id].model_copy(update={"address": shared})

    return [by_id[customer.id] for customer in customers]


def _apply_newcomer_ages(
    config: GeneratorConfig, customers: list[Customer], cohorts: _Cohorts
) -> list[Customer]:
    """Make the high-value-newcomer accounts genuinely new."""
    by_id = {customer.id: customer for customer in customers}

    for offset, customer_id in enumerate(sorted(cohorts.high_value_newcomers)):
        created = config.reference_date - timedelta(days=20 + offset)
        by_id[customer_id] = by_id[customer_id].model_copy(update={"created_at": created})

    return [by_id[customer.id] for customer in customers]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

#: How many orders each planted cohort needs for its pattern to be visible.
#: A serial refunder with three orders is not a serial refunder, it is noise.
_COHORT_ORDER_COUNTS: dict[str, tuple[int, int]] = {
    "serial_refunder": (10, 14),
    "wardrober": (6, 9),
    "ring_member": (3, 5),
    "delivery_claim_abuser": (5, 8),
    "high_value_newcomer": (1, 1),
}


def _build_orders(
    rng: random.Random,
    config: GeneratorConfig,
    customers: tuple[Customer, ...],
    products: tuple[Product, ...],
    cohorts: _Cohorts,
) -> tuple[Order, ...]:
    by_id = {customer.id: customer for customer in customers}
    orders: list[Order] = []
    counter = 0

    def emit(customer: Customer, *, high_value: bool = False) -> Order:
        nonlocal counter
        counter += 1
        return _make_order(rng, config, counter, customer, products, high_value=high_value)

    # Cohort orders first so their counts are guaranteed rather than left to the
    # weighted distribution below.
    cohort_members: list[tuple[str, str]] = []
    cohort_members += [(cid, "serial_refunder") for cid in sorted(cohorts.serial_refunders)]
    cohort_members += [(cid, "wardrober") for cid in sorted(cohorts.wardrobers)]
    cohort_members += [(cid, "ring_member") for cid in sorted(cohorts.ring_members)]
    cohort_members += [
        (cid, "delivery_claim_abuser") for cid in sorted(cohorts.delivery_claim_abusers)
    ]
    cohort_members += [(cid, "high_value_newcomer") for cid in sorted(cohorts.high_value_newcomers)]

    for member_id, role in cohort_members:
        low, high = _COHORT_ORDER_COUNTS[role]
        for _ in range(rng.randint(low, high)):
            orders.append(emit(by_id[member_id], high_value=role == "high_value_newcomer"))

    # Everyone else. Order volume per customer is long-tailed: most people buy
    # once or twice, a few buy constantly.
    ordinary = [customer for customer in customers if customer.id not in cohorts.all_flagged()]
    weights = [rng.paretovariate(1.6) for _ in ordinary]

    while len(orders) < config.orders:
        customer = rng.choices(ordinary, weights=weights, k=1)[0]
        orders.append(emit(customer))

    orders.sort(key=lambda order: order.placed_at)
    return tuple(orders)


def _make_order(
    rng: random.Random,
    config: GeneratorConfig,
    index: int,
    customer: Customer,
    products: tuple[Product, ...],
    *,
    high_value: bool,
) -> Order:
    earliest = customer.created_at + timedelta(days=1)
    latest = config.reference_date - timedelta(days=2)
    span_hours = max(int((latest - earliest).total_seconds() // 3600), 1)
    placed_at = earliest + timedelta(hours=rng.randint(0, span_hours))

    if high_value:
        # Top-decile basket: the most expensive things in the catalogue.
        expensive = sorted(products, key=lambda product: product.price, reverse=True)[:12]
        chosen = rng.sample(expensive, k=min(2, len(expensive)))
        lines = tuple(
            OrderLine(sku=product.sku, quantity=1, unit_price=product.price) for product in chosen
        )
        shipping = money(0)
    else:
        chosen = rng.sample(products, k=rng.randint(1, 4))
        lines = tuple(
            OrderLine(
                sku=product.sku,
                quantity=rng.choices((1, 2, 3), weights=(0.78, 0.17, 0.05), k=1)[0],
                unit_price=product.price,
            )
            for product in chosen
        )
        shipping = money(Decimal(rng.choice((0, 0, 299, 499))) / 100)

    return Order(
        id=ids.order_id(index),
        customer_id=customer.id,
        placed_at=placed_at,
        status=_order_status(rng, placed_at, config),
        lines=lines,
        shipping_cost=shipping,
        payment_method=rng.choices(tuple(PaymentMethod), weights=(0.74, 0.08, 0.13, 0.05), k=1)[0],
        delivery_address=customer.address,
    )


def _order_status(rng: random.Random, placed_at: datetime, config: GeneratorConfig) -> OrderStatus:
    age_days = (config.reference_date - placed_at).days

    if rng.random() < 0.03:
        return OrderStatus.CANCELLED
    if age_days < 2:
        return OrderStatus.PLACED
    if age_days < 5:
        return OrderStatus.SHIPPED
    return OrderStatus.DELIVERED


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

_SHIPPED_STATUSES = frozenset({OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.RETURNED})


def _build_shipments(
    rng: random.Random,
    config: GeneratorConfig,
    orders: tuple[Order, ...],
    cohorts: _Cohorts,
) -> tuple[Shipment, ...]:
    shipments: list[Shipment] = []
    counter = 0

    for order in orders:
        if order.status not in _SHIPPED_STATUSES:
            continue

        counter += 1
        carrier = rng.choice(_CARRIERS)
        shipped_at = order.placed_at + timedelta(hours=rng.randint(6, 72))
        delivered = order.status is not OrderStatus.SHIPPED
        delivered_at = shipped_at + timedelta(hours=rng.randint(18, 144)) if delivered else None

        # A customer who repeatedly reports parcels missing is claiming against
        # shipments the carrier can prove it handed over.
        abusive_claimant = order.customer_id in cohorts.delivery_claim_abusers
        signature = delivered and (abusive_claimant or rng.random() < 0.55)
        photo = delivered and (abusive_claimant or rng.random() < 0.45)

        # A genuine tail of lost parcels, so that a missing-parcel report is not
        # a perfect fraud signal by itself.
        lost = not delivered and rng.random() < 0.02

        shipments.append(
            Shipment(
                id=ids.shipment_id(counter),
                order_id=order.id,
                carrier=carrier,
                tracking_number=ids.tracking_number(carrier, counter),
                status=(
                    ShipmentStatus.DELIVERED
                    if delivered
                    else (ShipmentStatus.LOST if lost else ShipmentStatus.IN_TRANSIT)
                ),
                shipped_at=shipped_at,
                delivered_at=delivered_at,
                events=_delivery_events(rng, shipped_at, delivered_at, order.delivery_address.city),
                signature_captured=signature,
                delivery_photo=photo,
            )
        )

    return tuple(shipments)


def _delivery_events(
    rng: random.Random,
    shipped_at: datetime,
    delivered_at: datetime | None,
    city: str,
) -> tuple[DeliveryEvent, ...]:
    events = [
        DeliveryEvent(
            at=shipped_at,
            code=DeliveryEventCode.PICKED_UP,
            location="Gebze Sorting Centre",
            description="Parcel collected from the merchant",
        ),
        DeliveryEvent(
            at=shipped_at + timedelta(hours=rng.randint(2, 10)),
            code=DeliveryEventCode.DEPARTED_HUB,
            location="Gebze Sorting Centre",
            description="Departed sorting centre",
        ),
    ]

    if delivered_at is None:
        return tuple(events)

    events.append(
        DeliveryEvent(
            at=delivered_at - timedelta(hours=rng.randint(4, 20)),
            code=DeliveryEventCode.ARRIVED_HUB,
            location=f"{city} Distribution Centre",
            description="Arrived at destination hub",
        )
    )
    events.append(
        DeliveryEvent(
            at=delivered_at - timedelta(hours=rng.randint(1, 4)),
            code=DeliveryEventCode.OUT_FOR_DELIVERY,
            location=city,
            description="Out for delivery",
        )
    )
    events.append(
        DeliveryEvent(
            at=delivered_at,
            code=DeliveryEventCode.DELIVERED,
            location=city,
            description="Delivered to recipient",
        )
    )
    return tuple(events)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

_BASELINE_REASONS = (
    ReturnReason.CHANGED_MIND,
    ReturnReason.SIZE_ISSUE,
    ReturnReason.NOT_AS_DESCRIBED,
    ReturnReason.DAMAGED_ON_ARRIVAL,
    ReturnReason.WRONG_ITEM,
    ReturnReason.LATE_DELIVERY,
)
_BASELINE_REASON_WEIGHTS = (0.34, 0.24, 0.15, 0.13, 0.08, 0.06)


def _build_returns(
    rng: random.Random,
    config: GeneratorConfig,
    customers: tuple[Customer, ...],
    products: tuple[Product, ...],
    orders: tuple[Order, ...],
    shipments: tuple[Shipment, ...],
    cohorts: _Cohorts,
) -> tuple[ReturnRecord, ...]:
    delivery_by_order = {
        shipment.order_id: shipment.delivered_at
        for shipment in shipments
        if shipment.delivered_at is not None
    }
    price_by_sku = {product.sku: product.price for product in products}
    orders_by_customer: dict[str, list[Order]] = {}
    for order in orders:
        orders_by_customer.setdefault(order.customer_id, []).append(order)

    records: list[ReturnRecord] = []
    counter = 0

    def emit(
        order: Order,
        *,
        reason: ReturnReason,
        resolution: Resolution,
        days_after_delivery: int,
        note: str,
        sku: str | None = None,
    ) -> None:
        nonlocal counter
        delivered_at = delivery_by_order.get(order.id)
        if delivered_at is None:
            return

        counter += 1
        line = order.lines[0] if sku is None else (order.line_for(sku) or order.lines[0])
        amount = money(price_by_sku.get(line.sku, line.unit_price) * line.quantity)

        records.append(
            ReturnRecord(
                id=ids.return_id(counter),
                order_id=order.id,
                customer_id=order.customer_id,
                sku=line.sku,
                reason=reason,
                resolution=resolution,
                status=(
                    ReturnStatus.REJECTED
                    if resolution is Resolution.REJECTED
                    else ReturnStatus.COMPLETED
                ),
                amount=amount if resolution is not Resolution.REJECTED else money(0),
                created_at=delivered_at + timedelta(days=days_after_delivery),
                note=note,
            )
        )

    # --- planted patterns -------------------------------------------------

    for customer_id in sorted(cohorts.serial_refunders):
        customer_orders = orders_by_customer.get(customer_id, [])
        # Well over half of everything this account buys comes back.
        for order in customer_orders[: max(1, int(len(customer_orders) * 0.7))]:
            emit(
                order,
                reason=rng.choices(_BASELINE_REASONS, weights=_BASELINE_REASON_WEIGHTS, k=1)[0],
                resolution=Resolution.FULL_REFUND,
                days_after_delivery=rng.randint(2, 20),
                note="Refunded on request",
            )

    for customer_id in sorted(cohorts.wardrobers):
        for order in orders_by_customer.get(customer_id, []):
            dearest = max(order.lines, key=lambda line: line.unit_price)
            if dearest.unit_price < 150:
                continue
            emit(
                order,
                reason=rng.choice((ReturnReason.CHANGED_MIND, ReturnReason.SIZE_ISSUE)),
                resolution=Resolution.FULL_REFUND,
                # Right at the edge of the window, every time.
                days_after_delivery=rng.randint(RETURN_WINDOW_DAYS - 5, RETURN_WINDOW_DAYS - 1),
                note="Returned within window",
                sku=dearest.sku,
            )

    for ring in cohorts.address_rings:
        for member_id in ring:
            for order in orders_by_customer.get(member_id, [])[:2]:
                emit(
                    order,
                    reason=ReturnReason.NEVER_ARRIVED,
                    resolution=Resolution.FULL_REFUND,
                    days_after_delivery=rng.randint(1, 6),
                    note="Customer reports non-receipt",
                )

    for customer_id in sorted(cohorts.delivery_claim_abusers):
        for order in orders_by_customer.get(customer_id, []):
            emit(
                order,
                reason=ReturnReason.NEVER_ARRIVED,
                resolution=Resolution.FULL_REFUND,
                days_after_delivery=rng.randint(1, 4),
                note="Customer reports non-receipt despite delivery scan",
            )

    for customer_id in sorted(cohorts.high_value_newcomers):
        for order in orders_by_customer.get(customer_id, []):
            emit(
                order,
                reason=ReturnReason.DAMAGED_ON_ARRIVAL,
                resolution=Resolution.FULL_REFUND,
                days_after_delivery=rng.randint(0, 2),
                note="Damage reported immediately after delivery",
            )

    # --- ordinary returns -------------------------------------------------

    flagged = cohorts.all_flagged()
    for order in orders:
        if order.customer_id in flagged or order.id not in delivery_by_order:
            continue
        if rng.random() >= config.baseline_return_rate:
            continue

        reason = rng.choices(_BASELINE_REASONS, weights=_BASELINE_REASON_WEIGHTS, k=1)[0]
        emit(
            order,
            reason=reason,
            resolution=_baseline_resolution(rng, reason),
            days_after_delivery=rng.randint(1, RETURN_WINDOW_DAYS - 2),
            note="",
        )

    records.sort(key=lambda record: record.created_at)
    return tuple(records)


def _baseline_resolution(rng: random.Random, reason: ReturnReason) -> Resolution:
    """Resolutions an honest queue would produce.

    Not uniform: fault-based reasons are almost always resolved in the customer's
    favour, discretionary ones sometimes are not. Without that asymmetry the
    golden set would teach an agent that reason codes do not matter.
    """
    if reason in (ReturnReason.DAMAGED_ON_ARRIVAL, ReturnReason.WRONG_ITEM):
        return rng.choices(
            (Resolution.FULL_REFUND, Resolution.REPLACEMENT), weights=(0.6, 0.4), k=1
        )[0]
    if reason is ReturnReason.LATE_DELIVERY:
        return rng.choices(
            (Resolution.PARTIAL_REFUND, Resolution.STORE_CREDIT, Resolution.REJECTED),
            weights=(0.5, 0.3, 0.2),
            k=1,
        )[0]
    return rng.choices(
        (Resolution.FULL_REFUND, Resolution.STORE_CREDIT, Resolution.REJECTED),
        weights=(0.72, 0.16, 0.12),
        k=1,
    )[0]


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def _build_annotations(cohorts: _Cohorts, orders: tuple[Order, ...]) -> tuple[FraudAnnotation, ...]:
    orders_by_customer: dict[str, list[str]] = {}
    for order in orders:
        orders_by_customer.setdefault(order.customer_id, []).append(order.id)

    def order_ids_for(customer_ids: tuple[str, ...]) -> tuple[str, ...]:
        collected: list[str] = []
        for customer_id in customer_ids:
            collected.extend(orders_by_customer.get(customer_id, []))
        return tuple(sorted(collected))

    annotations: list[FraudAnnotation] = []

    for customer_id in sorted(cohorts.serial_refunders):
        annotations.append(
            FraudAnnotation(
                pattern=FraudPattern.SERIAL_REFUNDER,
                customer_ids=(customer_id,),
                order_ids=order_ids_for((customer_id,)),
                note="Majority of this account's orders end in a refund.",
            )
        )

    for customer_id in sorted(cohorts.wardrobers):
        annotations.append(
            FraudAnnotation(
                pattern=FraudPattern.WARDROBING,
                customer_ids=(customer_id,),
                order_ids=order_ids_for((customer_id,)),
                note="High-value items returned in the last days of the window, repeatedly.",
            )
        )

    for ring in cohorts.address_rings:
        annotations.append(
            FraudAnnotation(
                pattern=FraudPattern.ADDRESS_REUSE,
                customer_ids=tuple(sorted(ring)),
                order_ids=order_ids_for(ring),
                note="Separate accounts sharing one delivery address, all filing claims.",
            )
        )

    for customer_id in sorted(cohorts.delivery_claim_abusers):
        annotations.append(
            FraudAnnotation(
                pattern=FraudPattern.DELIVERY_CLAIM_ABUSE,
                customer_ids=(customer_id,),
                order_ids=order_ids_for((customer_id,)),
                note="Non-receipt claims against shipments with signature and photo evidence.",
            )
        )

    for customer_id in sorted(cohorts.high_value_newcomers):
        annotations.append(
            FraudAnnotation(
                pattern=FraudPattern.HIGH_VALUE_NEWCOMER,
                customer_ids=(customer_id,),
                order_ids=order_ids_for((customer_id,)),
                note="Days-old account, top-decile basket, immediate damage claim.",
            )
        )

    return tuple(annotations)


__all__ = [
    "DEFAULT_REFERENCE_DATE",
    "DEFAULT_SEED",
    "RETURN_WINDOW_DAYS",
    "Dataset",
    "GeneratorConfig",
    "generate",
]
