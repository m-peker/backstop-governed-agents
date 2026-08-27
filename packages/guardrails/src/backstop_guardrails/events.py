"""What a guardrail reports.

A guardrail never silently changes anything. It emits events, and the caller
decides. That separation matters more than it sounds: a detector that quietly
rewrote a ticket would make the audit trail a record of something the customer
never wrote, and a detector that quietly dropped a ticket would make a customer's
complaint disappear with no trace of why.

So every check produces a :class:`GuardrailEvent` carrying what it found, how
confident it is, and what it recommends. The pipeline aggregates them into a
:class:`GuardrailVerdict`, and the graph acts on that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Severity(IntEnum):
    """Ordered so that the worst finding in a set is ``max(severities)``."""

    INFO = 10
    LOW = 20
    MEDIUM = 30
    HIGH = 40
    CRITICAL = 50


class Action(StrEnum):
    """What the pipeline recommends doing about a finding."""

    ALLOW = "allow"
    """Nothing to do."""

    ANNOTATE = "annotate"
    """Proceed, but the finding is attached to the ticket for the record."""

    ESCALATE = "escalate"
    """Proceed only with a human. Used where a model should not be trusted to judge."""

    BLOCK = "block"
    """Do not process. The strongest recommendation an input guardrail makes."""


class Detector(StrEnum):
    """Which check produced a finding. Stable: it appears in metrics and audits."""

    LENGTH = "length"
    ENCODING = "encoding"
    LANGUAGE = "language"
    PII = "pii"
    INJECTION_HEURISTIC = "injection_heuristic"
    INJECTION_DENSITY = "injection_density"
    INJECTION_STRUCTURE = "injection_structure"
    CANARY_LEAK = "canary_leak"
    SCHEMA = "schema"
    GROUNDEDNESS = "groundedness"
    POLICY_CONFORMANCE = "policy_conformance"
    PII_LEAK = "pii_leak"
    TONE = "tone"


@dataclass(frozen=True, slots=True)
class GuardrailEvent:
    """One finding."""

    detector: Detector
    severity: Severity
    action: Action
    summary: str
    #: Where in the text, when the detector can say. Character offsets.
    span: tuple[int, int] | None = None
    #: Detector-specific detail. Must never contain the matched value itself when
    #: the detector is a PII detector - that would put the personal data straight
    #: into the event stream the detector exists to keep it out of.
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector.value,
            "severity": self.severity.name.lower(),
            "action": self.action.value,
            "summary": self.summary,
            "span": list(self.span) if self.span else None,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """The aggregate of every check in one pass."""

    events: tuple[GuardrailEvent, ...]

    @property
    def action(self) -> Action:
        """The strongest recommendation any detector made."""
        if not self.events:
            return Action.ALLOW
        ranking = {Action.ALLOW: 0, Action.ANNOTATE: 1, Action.ESCALATE: 2, Action.BLOCK: 3}
        return max((event.action for event in self.events), key=lambda a: ranking[a])

    @property
    def severity(self) -> Severity:
        return max((event.severity for event in self.events), default=Severity.INFO)

    @property
    def blocked(self) -> bool:
        return self.action is Action.BLOCK

    @property
    def needs_human(self) -> bool:
        return self.action in (Action.ESCALATE, Action.BLOCK)

    def by_detector(self, detector: Detector) -> tuple[GuardrailEvent, ...]:
        return tuple(event for event in self.events if event.detector is detector)

    def reasons(self) -> tuple[str, ...]:
        return tuple(event.summary for event in self.events)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "severity": self.severity.name.lower(),
            "events": [event.as_dict() for event in self.events],
        }


__all__ = ["Action", "Detector", "GuardrailEvent", "GuardrailVerdict", "Severity"]
