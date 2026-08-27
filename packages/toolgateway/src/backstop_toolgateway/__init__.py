"""The capability boundary.

Agents do not call tools. They ask the gateway to call a tool, and the gateway
decides. Scopes, approval, idempotency, rate limits and the audit chain all live
here, in deterministic code that no amount of persuasion reaches.
"""

from backstop_toolgateway.approval import ApprovalAuthority, ApprovalToken
from backstop_toolgateway.audit import AuditChain, AuditEntry, Outcome
from backstop_toolgateway.canonical import FixedClock, canonical_json, digest, system_clock
from backstop_toolgateway.errors import (
    ApprovalInvalid,
    ApprovalRequired,
    BudgetExceeded,
    GatewayError,
    KillSwitchEngaged,
    RateLimited,
    ScopeDenied,
    ToolExecutionFailed,
    UnknownTool,
)
from backstop_toolgateway.gateway import StaticPolicy, ToolGateway, ToolHandler, ToolResult
from backstop_toolgateway.idempotency import MemoryIdempotencyStore, idempotency_key
from backstop_toolgateway.principal import (
    ALL_PRINCIPALS,
    GRAPH_EXECUTOR,
    GRAPH_INVESTIGATOR,
    GRAPH_POLICY_READER,
    Principal,
)
from backstop_toolgateway.ratelimit import RateLimiter
from backstop_toolgateway.scopes import DEFAULT_REGISTRY, READ_ONLY, Scope, ToolRegistry, ToolSpec

__all__ = [
    "ALL_PRINCIPALS",
    "DEFAULT_REGISTRY",
    "GRAPH_EXECUTOR",
    "GRAPH_INVESTIGATOR",
    "GRAPH_POLICY_READER",
    "READ_ONLY",
    "ApprovalAuthority",
    "ApprovalInvalid",
    "ApprovalRequired",
    "ApprovalToken",
    "AuditChain",
    "AuditEntry",
    "BudgetExceeded",
    "FixedClock",
    "GatewayError",
    "KillSwitchEngaged",
    "MemoryIdempotencyStore",
    "Outcome",
    "Principal",
    "RateLimited",
    "RateLimiter",
    "Scope",
    "ScopeDenied",
    "StaticPolicy",
    "ToolExecutionFailed",
    "ToolGateway",
    "ToolHandler",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "UnknownTool",
    "canonical_json",
    "digest",
    "idempotency_key",
    "system_clock",
]
