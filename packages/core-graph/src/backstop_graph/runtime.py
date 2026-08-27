"""What the graph needs to do its work.

Assembled once and closed over by the nodes. Passing dependencies explicitly - as
opposed to reaching for module globals inside a node - is what lets a test build a
graph with a stubbed model, an in-memory gateway and a fixed clock, and get the
same code path production takes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backstop_guardrails import InputGuardrail
from backstop_llm import LLMClient
from backstop_policy import PolicyEngine
from backstop_toolgateway import ApprovalAuthority, ToolGateway


class Deliberator(Protocol):
    """The deliberation room, as the graph sees it.

    A Protocol rather than an import so that ``backstop-graph`` does not depend on
    ``backstop-deliberation``. The graph knows there is something it can hand a hard
    case to; it does not know that thing is AutoGen, and swapping the engine is
    therefore a wiring change rather than a graph change. That independence is
    also what makes the two-engine comparison possible at all.
    """

    async def deliberate(self, *, brief: str) -> object: ...


@dataclass(frozen=True, slots=True)
class Runtime:
    """Everything the nodes reach for."""

    gateway: ToolGateway
    llm: LLMClient
    policy: PolicyEngine
    input_guard: InputGuardrail
    approvals: ApprovalAuthority

    #: Mirrors the gateway's own ceiling. Held here too so the policy engine can
    #: reach the same conclusion the gateway will, *before* a write is attempted -
    #: which is what turns "the gateway refused" into "the graph paused for a
    #: human". Two checks of the same rule, deliberately, at different moments.
    auto_approve_ceiling: Decimal = Decimal("75.00")

    #: Below this, an assessment is treated as too uncertain to act on regardless
    #: of what it proposes.
    min_confidence: float = 0.55

    #: The deliberation room. When absent, cases the policy cannot settle go
    #: straight to a human instead of being argued first - a degradation, not a
    #: failure, and the graph says which happened.
    room: Deliberator | None = None


__all__ = ["Runtime"]
