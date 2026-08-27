"""Identifier formatting.

Kept in one place so that the pattern in :mod:`backstop_domain.models` and the
generator can never disagree about width or prefix.
"""

from __future__ import annotations

from backstop_domain.models import ProductCategory

_CATEGORY_CODE: dict[ProductCategory, str] = {
    ProductCategory.APPAREL: "APP",
    ProductCategory.HOME: "HOM",
    ProductCategory.ELECTRONICS: "ELC",
    ProductCategory.BEAUTY: "BTY",
    ProductCategory.GROCERY: "GRC",
}


def customer_id(index: int) -> str:
    return f"CUS-{index:05d}"


def order_id(index: int) -> str:
    return f"ORD-{index:07d}"


def shipment_id(index: int) -> str:
    return f"SHP-{index:07d}"


def return_id(index: int) -> str:
    return f"RET-{index:06d}"


def product_sku(category: ProductCategory, index: int) -> str:
    return f"SKU-{_CATEGORY_CODE[category]}-{index:04d}"


def tracking_number(carrier: str, index: int) -> str:
    prefix = "".join(part[0] for part in carrier.split()).upper()[:2]
    return f"{prefix}{index:09d}TR"


__all__ = [
    "customer_id",
    "order_id",
    "product_sku",
    "return_id",
    "shipment_id",
    "tracking_number",
]
