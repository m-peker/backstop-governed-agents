"""Binding the MCP servers to the tool gateway.

The gateway calls handlers; the servers expose MCP tools. This is the adapter, and
it comes in two forms.

:func:`local_handlers` runs the servers **in process**. No subprocess, no stdio, no
serialisation round trip. That is what the tests, the labs and the demo use, and it
is why the whole tool plane is exercisable in under a second.

Phase 2 adds the out-of-process form, where each server runs as its own container
with its own network policy. The gateway does not change: it calls a handler and
gets a result either way. Keeping that seam clean now is what makes the switch a
configuration change later rather than a rewrite.

Deliberately no gateway import. The returned callables are structurally compatible
with ``backstop_toolgateway.ToolHandler``, so the adapter needs no dependency on the
package it adapts to - and the servers stay usable by anything else that speaks MCP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from backstop_mcp.servers import catalog, orders, payments, policy, shipping

Handler = Callable[[Mapping[str, Any]], Awaitable[Any]]

#: Server name to instance, matching the ``server`` field on each registry entry.
SERVERS: dict[str, MCPServer[Any]] = {
    "orders": orders.server,
    "shipping": shipping.server,
    "catalog": catalog.server,
    "policy": policy.server,
    "payments": payments.server,
}


def _handler_for(server: MCPServer[Any], tool_name: str) -> Handler:
    async def handler(args: Mapping[str, Any]) -> Any:
        result = await server.call_tool(tool_name, dict(args))

        # A tool that stops to ask the client a question has no meaning behind the
        # gateway: there is no interactive client on this path, and the graph's
        # own human-in-the-loop mechanism is the approval interrupt.
        if not isinstance(result, CallToolResult):
            raise RuntimeError(f"{tool_name} requested client input, which is not supported here")

        if result.is_error:
            raise RuntimeError(f"{tool_name} returned an error: {result.content}")

        return result.structured_content

    handler.__name__ = f"{tool_name}_handler"
    return handler


async def local_handlers() -> dict[str, Handler]:
    """Every tool on every server, bound to an in-process handler.

    Returns:
        Tool name to handler. Pass straight to ``ToolGateway(handlers=...)``; the
        gateway rejects any name its registry has not declared, so a server that
        grows an undeclared tool fails loudly at construction rather than becoming
        quietly reachable.
    """
    handlers: dict[str, Handler] = {}
    for server in SERVERS.values():
        for tool in await server.list_tools():
            handlers[tool.name] = _handler_for(server, tool.name)
    return handlers


__all__ = ["SERVERS", "Handler", "local_handlers"]
