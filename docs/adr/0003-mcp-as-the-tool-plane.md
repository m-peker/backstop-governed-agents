# ADR 0003 — MCP as the tool plane

- Status: accepted
- Date: 2026-08-25

## Context

Two orchestration engines need the same capabilities. Tools must be independently testable,
independently deployable, and enforceable at a boundary the model cannot reason its way past.

## Decision

All capabilities are exposed as Model Context Protocol servers. Neither orchestrator binds
tools natively. Both go through the tool gateway, which speaks MCP to the servers.

## Consequences

- Swapping the reasoning engine changes nothing about the capability surface.
- Each server is a process with its own container, scopes, and network policy.
- Tools are testable without an LLM in the loop.
- Cost: a process boundary and serialization overhead per call. Acceptable.

## Alternatives considered

- **Framework-native tool decorators.** Duplicated per framework, untestable in isolation,
  and no natural place to enforce scopes. Rejected.
- **A plain internal HTTP API.** Workable, but forfeits the ecosystem, the introspection
  tooling, and the portability that make this interesting as a reference implementation.
