"""The Backstop tool plane.

Five MCP servers, one process each, sharing one domain package. Both the
LangGraph resolution path and the AutoGen deliberation room bind to these same
servers through the tool gateway - swapping the reasoning engine changes nothing
about what the system is able to do.
"""

__version__ = "0.1.0"

SERVER_MODULES = (
    "backstop_mcp.servers.orders",
    "backstop_mcp.servers.shipping",
    "backstop_mcp.servers.catalog",
    "backstop_mcp.servers.policy",
    "backstop_mcp.servers.payments",
)

__all__ = ["SERVER_MODULES", "__version__"]
