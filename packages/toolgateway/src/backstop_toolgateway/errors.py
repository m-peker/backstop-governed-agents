"""Gateway refusals.

Every refusal is a distinct type carrying the facts a caller, an audit entry and a
customer-facing message all need. That matters more than it might look: the graph
reacts differently to "you lack the scope" (a wiring bug, fail the ticket) than to
"this needs human approval" (expected, pause the graph) or "rate limited" (retry).

A refusal is never expressed as a ``None`` return or a falsy result. Silent
failures in a capability boundary are how an agent ends up believing it did
something it did not do.
"""

from __future__ import annotations

from decimal import Decimal


class GatewayError(Exception):
    """Base class for every refusal at the capability boundary."""

    #: Stable machine-readable code. Used in audit entries and metrics, so it is
    #: part of the contract and must not change casually.
    code = "gateway_error"
    #: Whether the same call might succeed later without anything else changing.
    retryable = False

    def __init__(self, message: str, *, tool: str | None = None) -> None:
        super().__init__(message)
        self.tool = tool

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": str(self), "tool": self.tool}


class UnknownTool(GatewayError):
    """The tool is not in the registry.

    Frequently the signature of an injected instruction persuading a model to call
    something that does not exist, so it is logged at a higher severity than a
    typo would deserve.
    """

    code = "unknown_tool"


class ScopeDenied(GatewayError):
    """The principal does not hold the scope this tool requires."""

    code = "scope_denied"

    def __init__(self, message: str, *, tool: str, required: str, held: frozenset[str]) -> None:
        super().__init__(message, tool=tool)
        self.required = required
        self.held = held

    def as_dict(self) -> dict[str, object]:
        return {**super().as_dict(), "required": self.required, "held": sorted(self.held)}


class ApprovalRequired(GatewayError):
    """A human must approve this call before it can proceed.

    Not an error in the usual sense. The graph catches it, pauses on an
    ``interrupt()`` and resumes with a token once someone has decided.
    """

    code = "approval_required"

    def __init__(
        self,
        message: str,
        *,
        tool: str,
        amount: Decimal | None = None,
        ceiling: Decimal | None = None,
    ) -> None:
        super().__init__(message, tool=tool)
        self.amount = amount
        self.ceiling = ceiling

    def as_dict(self) -> dict[str, object]:
        return {
            **super().as_dict(),
            "amount": str(self.amount) if self.amount is not None else None,
            "ceiling": str(self.ceiling) if self.ceiling is not None else None,
        }


class ApprovalInvalid(GatewayError):
    """An approval token was presented but does not authorise this call.

    Covers a bad signature, an expired token, and - the interesting case - a token
    that is validly signed but bound to a different ticket, a different tool or
    different arguments. That binding is what stops an approval for a EUR 20
    refund being replayed against a EUR 2,000 one.
    """

    code = "approval_invalid"


class RateLimited(GatewayError):
    """Too many calls in the window."""

    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, tool: str, retry_after_seconds: float) -> None:
        super().__init__(message, tool=tool)
        self.retry_after_seconds = retry_after_seconds

    def as_dict(self) -> dict[str, object]:
        return {**super().as_dict(), "retry_after_seconds": self.retry_after_seconds}


class BudgetExceeded(GatewayError):
    """The tenant has spent its allowance for the period."""

    code = "budget_exceeded"


class KillSwitchEngaged(GatewayError):
    """Every write tool is refused.

    Checked before scopes, before approval, before anything. A kill switch that
    can be reasoned around is not a kill switch.
    """

    code = "kill_switch_engaged"


class ToolExecutionFailed(GatewayError):
    """The underlying tool raised.

    The original exception is attached but is deliberately not re-raised: an
    upstream stack trace reaching a model context is an information leak, and a
    model that sees an exception message will try to work around it.
    """

    code = "tool_execution_failed"
    retryable = True

    def __init__(self, message: str, *, tool: str, cause: BaseException | None = None) -> None:
        super().__init__(message, tool=tool)
        self.cause = cause


__all__ = [
    "ApprovalInvalid",
    "ApprovalRequired",
    "BudgetExceeded",
    "GatewayError",
    "KillSwitchEngaged",
    "RateLimited",
    "ScopeDenied",
    "ToolExecutionFailed",
    "UnknownTool",
]
