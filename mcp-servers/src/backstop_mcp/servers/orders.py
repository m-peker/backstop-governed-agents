"""Orders MCP server.

Reads orders, order history and customer profiles.

The profile tool is the interesting one. It returns computed signals - tenure,
return rate, prior non-receipt claims, how many accounts share this delivery
address - rather than raw rows for a model to aggregate. Those are exactly the
signals a fraud investigator needs, and they are deliberately *signals*, not
verdicts: the tool never says "this customer is abusing returns". It says the
account is 20 days old, has a 0.86 return rate, and shares its address with two
other accounts. What that means is the agent's judgement, recorded and reviewable.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from backstop_mcp.context import NotFound, store

server = MCPServer(
    "backstop-orders",
    version="0.1.0",
    instructions=(
        "Order and customer records for retail customer operations. "
        "Read-only. All amounts are in EUR."
    ),
)


@server.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Fetch one order with its lines, totals and delivery address.

    Args:
        order_id: Order identifier, for example ORD-0001234.
    """
    order = store().get_order(order_id)
    if order is None:
        raise NotFound(f"no order with id {order_id}")

    return {
        "order_id": order.id,
        "customer_id": order.customer_id,
        "placed_at": order.placed_at.isoformat(),
        "status": order.status.value,
        "currency": order.currency,
        "payment_method": order.payment_method.value,
        "goods_total": str(order.goods_total),
        "shipping_cost": str(order.shipping_cost),
        "total": str(order.total),
        "lines": [
            {
                "sku": line.sku,
                "quantity": line.quantity,
                "unit_price": str(line.unit_price),
                "line_total": str(line.line_total),
            }
            for line in order.lines
        ],
        "delivery_address": {
            "line1": order.delivery_address.line1,
            "city": order.delivery_address.city,
            "postal_code": order.delivery_address.postal_code,
            "country": order.delivery_address.country,
        },
    }


@server.tool()
def list_customer_orders(customer_id: str, limit: int = 20) -> dict[str, Any]:
    """List a customer's orders, newest first.

    Args:
        customer_id: Customer identifier, for example CUS-00042.
        limit: Maximum orders to return. Capped at 50 by the store.
    """
    if store().get_customer(customer_id) is None:
        raise NotFound(f"no customer with id {customer_id}")

    orders = store().list_customer_orders(customer_id, limit=limit)
    return {
        "customer_id": customer_id,
        "returned": len(orders),
        "orders": [
            {
                "order_id": order.id,
                "placed_at": order.placed_at.isoformat(),
                "status": order.status.value,
                "total": str(order.total),
                "line_count": len(order.lines),
            }
            for order in orders
        ],
    }


@server.tool()
def get_customer_profile(customer_id: str) -> dict[str, Any]:
    """Customer profile with tenure, spend, return rate and claim history.

    Returns computed signals, not conclusions. Interpreting them is the caller's
    job and must be recorded as reasoning.

    Args:
        customer_id: Customer identifier, for example CUS-00042.
    """
    profile = store().get_customer_profile(customer_id)
    if profile is None:
        raise NotFound(f"no customer with id {customer_id}")

    return {
        "customer_id": profile.customer_id,
        "name": profile.name,
        "email": profile.email,
        "tier": profile.tier.value,
        "created_at": profile.created_at.isoformat(),
        "tenure_days": profile.tenure_days,
        "is_new_account": profile.is_new_account,
        "total_orders": profile.total_orders,
        "delivered_orders": profile.delivered_orders,
        "total_returns": profile.total_returns,
        "return_rate": profile.return_rate,
        "lifetime_value": str(profile.lifetime_value),
        "never_arrived_claims": profile.never_arrived_claims,
        "accounts_at_this_address": profile.accounts_at_this_address,
        "city": profile.address.city,
    }


@server.tool()
def list_customer_returns(customer_id: str, limit: int = 20) -> dict[str, Any]:
    """A customer's prior returns, newest first.

    ``days_after_delivery`` is included because when a claim was made is often
    more informative than what it claimed.

    Args:
        customer_id: Customer identifier, for example CUS-00042.
        limit: Maximum records to return. Capped at 50 by the store.
    """
    if store().get_customer(customer_id) is None:
        raise NotFound(f"no customer with id {customer_id}")

    entries = store().list_returns_for_customer(customer_id, limit=limit)
    return {
        "customer_id": customer_id,
        "returned": len(entries),
        "returns": [
            {
                "return_id": entry.return_id,
                "order_id": entry.order_id,
                "sku": entry.sku,
                "reason": entry.reason.value,
                "resolution": entry.resolution,
                "amount": str(entry.amount),
                "created_at": entry.created_at.isoformat(),
                "days_after_delivery": entry.days_after_delivery,
            }
            for entry in entries
        ],
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
