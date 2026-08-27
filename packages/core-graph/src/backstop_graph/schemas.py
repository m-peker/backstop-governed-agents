"""What a model is allowed to say.

Each schema here is sent to the provider as a strict JSON schema, so the model is
constrained at decode time rather than asked politely in a prompt. A malformed
decision is not something the guardrail plane has to catch: it cannot be produced.

Two design choices repeat across these schemas.

**Every decision carries its citations.** ``cited_clauses`` is required, and the
output guardrail checks each entry against what was actually retrieved. A model
that wants to reach a conclusion has to name the clause it came from.

**Escalation is a first-class answer, not a failure.** ``needs_human`` and the
``escalate`` resolution exist so that "I should not decide this" is something the
model can say cleanly, rather than something it expresses by producing a
low-confidence guess.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    # extra="forbid" becomes additionalProperties:false in the JSON schema, which
    # is what the provider's strict mode requires.
    model_config = ConfigDict(extra="forbid")


class TicketIntent(StrEnum):
    DAMAGED_ON_ARRIVAL = "damaged_on_arrival"
    NEVER_ARRIVED = "never_arrived"
    WRONG_ITEM = "wrong_item"
    LATE_DELIVERY = "late_delivery"
    CHANGED_MIND = "changed_mind"
    SIZE_ISSUE = "size_issue"
    NOT_AS_DESCRIBED = "not_as_described"
    OTHER = "other"


class ProposedResolution(StrEnum):
    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    REPLACEMENT = "replacement"
    STORE_CREDIT = "store_credit"
    REJECTED = "rejected"
    ESCALATE = "escalate"


class Classification(Strict):
    """What the customer is asking for, and which records it concerns."""

    intent: TicketIntent
    confidence: float = Field(ge=0, le=1)

    order_id: str | None = Field(
        default=None,
        description="Order reference quoted in the message, in the form ORD-0000000. "
        "Null when the message does not quote one.",
    )

    requests_human: bool = Field(
        description="Whether the customer explicitly asked for a person to review "
        "their case. RP-13.2 requires such a request to be honoured."
    )

    summary: str = Field(
        max_length=400,
        description="One or two sentences restating the complaint in neutral terms. "
        "Placeholders such as <PERSON_1> must be reproduced verbatim.",
    )


class Assessment(Strict):
    """The proposed resolution, with the reasoning that produced it."""

    resolution: ProposedResolution
    amount_eur: str | None = Field(
        default=None,
        description="Amount as a decimal string, for example '49.90'. Null for "
        "resolutions that move no money.",
    )
    confidence: float = Field(ge=0, le=1)

    cited_clauses: list[str] = Field(
        description="Clause identifiers supporting this resolution, drawn only from "
        "the clauses provided. Never invent one.",
    )

    rationale: str = Field(
        max_length=1200,
        description="Why this resolution follows from the facts and the cited clauses.",
    )

    needs_human: bool = Field(
        description="True when the clauses conflict, the facts are incomplete, or "
        "the case turns on judgement the policy does not settle. Saying so is a "
        "correct answer, not a failure."
    )

    concerns: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Anything that should be recorded but does not change the "
        "resolution, such as an abuse indicator observed in the facts.",
    )


class ReplyDraft(Strict):
    """The customer-facing message."""

    reply: str = Field(
        max_length=1600,
        description="The message to send. Address the customer using the "
        "<PERSON_n> placeholder exactly as it appears; it is resolved to their "
        "real name after this text leaves the model.",
    )
    tone: str = Field(description="One word: apologetic, neutral, or firm.")
    mentions_amount: bool


class DeliberationVerdict(Strict):
    """The arbiter's conclusion after the room has argued."""

    resolution: ProposedResolution
    amount_eur: str | None = None
    cited_clauses: list[str]
    rationale: str = Field(max_length=1200)
    dissent: str = Field(
        default="",
        max_length=600,
        description="The strongest argument against this conclusion. Recorded "
        "because a decision that suppressed the counter-argument cannot be reviewed.",
    )
    confidence: float = Field(ge=0, le=1)


class DeliberationTurn(Strict):
    """One agent's contribution to the room."""

    argument: str = Field(max_length=900)
    cited_clauses: list[str] = Field(default_factory=list)
    recommends: ProposedResolution


__all__ = [
    "Assessment",
    "Classification",
    "DeliberationTurn",
    "DeliberationVerdict",
    "ProposedResolution",
    "ReplyDraft",
    "Strict",
    "TicketIntent",
]
