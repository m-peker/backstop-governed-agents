"""Types shared by every provider.

The unit of work is a :class:`Completion`: a typed result plus the usage and cost
that producing it incurred. Cost is not an afterthought bolted on for a dashboard -
it rides on every response, because "what did this ticket cost" has to be
answerable from the audit trail rather than reconstructed from provider invoices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role.value, "content": self.content}


class TaskClass(StrEnum):
    """What a call is for. The router maps this to a model tier.

    Naming the *task* rather than the model is what makes the routing table a
    reviewable policy instead of a scatter of model strings across the codebase.
    Changing which model classifies intent is then one line in one file.
    """

    DETECT = "detect"
    """Guardrail detectors. High volume, low stakes, cheapest tier."""

    CLASSIFY = "classify"
    """Intent classification. High volume, cheap tier."""

    ASSESS = "assess"
    """The resolution decision. Low volume, high stakes, strong tier."""

    DELIBERATE = "deliberate"
    """A voice in the deliberation room. Strong tier, capped rounds."""

    ARBITRATE = "arbitrate"
    """The arbiter's structured verdict. Strong tier."""

    COMPOSE = "compose"
    """The customer-facing reply. Strong tier - tone matters and is judged."""

    JUDGE = "judge"
    """LLM-as-judge in the eval harness. Strong tier, never in the request path."""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class Completion[T: BaseModel]:
    """One model response, with everything needed to account for it."""

    value: T
    text: str
    model: str
    provider: str
    task: TaskClass
    usage: Usage
    cost_usd: Decimal
    latency_ms: float

    #: Set when the primary provider failed and a fallback answered. Recorded in
    #: the audit entry: "which model decided this" must survive a failover.
    fell_back_from: str | None = None

    def as_audit_fields(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "task": self.task.value,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cost_usd": str(self.cost_usd),
            "latency_ms": round(self.latency_ms, 1),
            "fell_back_from": self.fell_back_from,
        }


@dataclass(slots=True)
class CostLedger:
    """Running spend for one unit of work - usually one ticket."""

    entries: list[tuple[str, Decimal]] = field(default_factory=list)

    def record(self, label: str, amount: Decimal) -> None:
        self.entries.append((label, amount))

    @property
    def total(self) -> Decimal:
        return sum((amount for _, amount in self.entries), Decimal("0"))

    def breakdown(self) -> dict[str, str]:
        totals: dict[str, Decimal] = {}
        for label, amount in self.entries:
            totals[label] = totals.get(label, Decimal("0")) + amount
        return {label: str(amount) for label, amount in sorted(totals.items())}


class LLMError(RuntimeError):
    """A provider call failed after the router exhausted its fallbacks."""


class BudgetExhausted(LLMError):
    """The spend ceiling for the period has been reached.

    Distinct from a provider failure: retrying will not help, and the correct
    response is to degrade to human handling rather than to keep trying.
    """


__all__ = [
    "BudgetExhausted",
    "Completion",
    "CostLedger",
    "LLMError",
    "Message",
    "Role",
    "TaskClass",
    "Usage",
]
