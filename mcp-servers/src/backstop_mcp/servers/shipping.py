"""Shipping MCP server.

Delivery status and the evidence behind it.

``evidence_strength`` is computed here rather than left to the caller, because the
distinction it encodes is the one that decides most non-receipt claims and it is
stated in policy (DP-3.1 through DP-3.3), not invented by an agent. A scan alone
is weak evidence; a scan with a signature or a photograph is strong. Getting that
wrong in either direction is expensive: refuse a genuine customer, or pay out on
every claim.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from backstop_domain.models import Shipment, ShipmentStatus
from backstop_mcp.context import NotFound, store

server = MCPServer(
    "backstop-shipping",
    version="0.1.0",
    instructions=(
        "Carrier tracking and delivery evidence. Read-only. "
        "Evidence strength follows delivery policy DP-3."
    ),
)


def _evidence_strength(shipment: Shipment) -> str:
    """Classify delivery evidence per DP-3.

    Returns one of ``none``, ``weak`` or ``strong``. ``weak`` means the carrier
    believes it delivered but cannot show receipt - DP-3.2 - which is a different
    thing from no delivery at all.
    """
    if shipment.status is not ShipmentStatus.DELIVERED:
        return "none"
    if shipment.signature_captured or shipment.delivery_photo:
        return "strong"
    return "weak"


def _shipment_payload(shipment: Shipment) -> dict[str, Any]:
    return {
        "shipment_id": shipment.id,
        "order_id": shipment.order_id,
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status.value,
        "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
        "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
        "signature_captured": shipment.signature_captured,
        "delivery_photo": shipment.delivery_photo,
        "evidence_strength": _evidence_strength(shipment),
    }


@server.tool()
def track_shipment(order_id: str) -> dict[str, Any]:
    """Shipment status and delivery evidence for an order.

    Args:
        order_id: Order identifier, for example ORD-0001234.
    """
    if store().get_order(order_id) is None:
        raise NotFound(f"no order with id {order_id}")

    shipment = store().get_shipment_for_order(order_id)
    if shipment is None:
        # A real state, not an error: the order exists but has not shipped.
        return {
            "order_id": order_id,
            "shipment": None,
            "status": "not_dispatched",
            "evidence_strength": "none",
        }

    return {"order_id": order_id, "shipment": _shipment_payload(shipment)}


@server.tool()
def get_delivery_events(shipment_id: str) -> dict[str, Any]:
    """Full carrier event timeline for a shipment, oldest first.

    Args:
        shipment_id: Shipment identifier, for example SHP-0001234.
    """
    shipment = store().get_shipment(shipment_id)
    if shipment is None:
        raise NotFound(f"no shipment with id {shipment_id}")

    return {
        "shipment_id": shipment.id,
        "order_id": shipment.order_id,
        "carrier": shipment.carrier,
        "status": shipment.status.value,
        "evidence_strength": _evidence_strength(shipment),
        "events": [
            {
                "at": event.at.isoformat(),
                "code": event.code.value,
                "location": event.location,
                "description": event.description,
            }
            for event in sorted(shipment.events, key=lambda item: item.at)
        ],
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
