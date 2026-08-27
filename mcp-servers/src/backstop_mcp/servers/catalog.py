"""Catalogue MCP server.

Product details and return eligibility.

``get_return_eligibility`` reports facts and stops: the window, the elapsed days,
and a list of machine-readable ``blocking_conditions``. It never returns a
decision. The distinction matters because the exclusions in policy have exceptions
- RP-6.4 says a product exclusion never defeats a claim for a faulty or damaged
item - and encoding that exception here would put half the decision in a data
tool, where nobody would think to look for it. Eligibility facts belong to the
catalogue; the decision belongs to the policy engine.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from backstop_mcp.context import NotFound, store

server = MCPServer(
    "backstop-catalog",
    version="0.1.0",
    instructions=(
        "Product catalogue and return-window facts. Read-only. "
        "Reports eligibility conditions, never a resolution."
    ),
)


@server.tool()
def get_product(sku: str) -> dict[str, Any]:
    """Product details including the flags that affect returnability.

    Args:
        sku: Product identifier, for example SKU-APP-0117.
    """
    product = store().get_product(sku)
    if product is None:
        raise NotFound(f"no product with sku {sku}")

    return {
        "sku": product.sku,
        "name": product.name,
        "category": product.category.value,
        "price": str(product.price),
        "weight_kg": product.weight_kg,
        "final_sale": product.final_sale,
        "hygiene_sensitive": product.hygiene_sensitive,
        "perishable": product.perishable,
    }


@server.tool()
def get_return_eligibility(order_id: str, sku: str) -> dict[str, Any]:
    """Whether an item is inside its return window, and what would block a return.

    ``blocking_conditions`` lists machine-readable reasons a *standard* return
    would not apply. It is not a refusal: several conditions are overridden by
    policy when the item was faulty, damaged on arrival or simply the wrong item.

    Args:
        order_id: Order identifier, for example ORD-0001234.
        sku: Product identifier on that order.
    """
    eligibility = store().get_return_eligibility(order_id, sku)
    if eligibility is None:
        raise NotFound(f"order {order_id} has no line for sku {sku}")

    return {
        "order_id": eligibility.order_id,
        "sku": eligibility.sku,
        "delivered_at": (
            eligibility.delivered_at.isoformat() if eligibility.delivered_at else None
        ),
        "days_since_delivery": eligibility.days_since_delivery,
        "window_days": eligibility.window_days,
        "within_window": eligibility.within_window,
        "final_sale": eligibility.final_sale,
        "hygiene_sensitive": eligibility.hygiene_sensitive,
        "perishable": eligibility.perishable,
        "blocking_conditions": list(eligibility.blocking_conditions),
        "note": (
            "Blocking conditions describe the standard case. Policy overrides them "
            "for faulty, damaged-on-arrival or wrong items."
        ),
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
