"""The graph's state.

Every field here is JSON-serialisable, and that constraint drives the design. The
state is checkpointed after every node so a ticket can pause for days waiting on a
human and resume exactly where it stopped; anything that cannot survive a
round-trip through the checkpointer cannot live in the state.

So the PII vault is stored as a plain mapping rather than as its class, tool
results are stored as the dicts the tools returned, and the policy decision is
stored as its explained form. Rehydrating a rich object from these is cheap; the
reverse - discovering after a crash that half the state did not serialise - is not.

One field deserves attention: ``raw_message`` holds exactly what the customer sent
and is **never** placed in a prompt. It exists so the audit record shows the real
message rather than a normalised approximation of it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, TypedDict


def _replace(_current: Any, incoming: Any) -> Any:
    """Last write wins. The default, stated explicitly for readability."""
    return incoming


def _extend(current: list[Any] | None, incoming: list[Any] | None) -> list[Any]:
    """Concatenate. Used where concurrent nodes each contribute entries.

    ``gather_facts`` fans out, and without this reducer the branches would
    overwrite one another's guardrail events and audit references.
    """
    return [*(current or []), *(incoming or [])]


def _merge(current: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    return {**(current or {}), **(incoming or {})}


class Status(StrEnum):
    """Where a ticket is. Drives the console and the approval queue."""

    RECEIVED = "received"
    BLOCKED = "blocked"
    """An input guardrail refused it. It never reached a model."""

    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (Status.BLOCKED, Status.RESOLVED, Status.REJECTED, Status.FAILED)


class ResolutionState(TypedDict, total=False):
    """One ticket, from arrival to a closed decision."""

    # -- identity ---------------------------------------------------------
    ticket_id: str
    channel: str
    status: str

    # -- input ------------------------------------------------------------
    raw_message: str
    """Exactly what arrived. For the record only; never sent to a model."""

    safe_message: str
    """Normalised and PII-tokenised. This is what a prompt may carry."""

    pii_vault: Annotated[dict[str, str], _merge]
    """Placeholder to value. Held beside the prompt, never inside it."""

    spotlight_marker: str
    canary: str

    # -- findings ---------------------------------------------------------
    guardrail_events: Annotated[list[dict[str, Any]], _extend]

    # -- classification ---------------------------------------------------
    intent: str
    intent_confidence: float
    order_id: str | None
    customer_id: str | None

    # -- facts ------------------------------------------------------------
    facts: Annotated[dict[str, Any], _merge]
    """Tool output, keyed by tool name. Merged because gather_facts fans out."""

    fact_gaps: Annotated[list[str], _extend]
    """Tools that failed. A missing fact degrades the decision rather than the ticket."""

    # -- policy -----------------------------------------------------------
    policy_refs: list[dict[str, Any]]
    retrieved_clause_ids: list[str]

    # -- decision ---------------------------------------------------------
    assessment: dict[str, Any]
    policy_decision: dict[str, Any]
    deliberation: dict[str, Any]

    # -- human ------------------------------------------------------------
    approval: dict[str, Any] | None
    approval_request: dict[str, Any] | None

    # -- outcome ----------------------------------------------------------
    execution: dict[str, Any] | None
    reply: str | None
    released_reply: str | None

    # -- accounting -------------------------------------------------------
    audit_sequences: Annotated[list[int], _extend]
    cost_usd: str
    model_calls: Annotated[list[dict[str, Any]], _extend]

    # -- failure ----------------------------------------------------------
    failure: str | None


def initial_state(*, ticket_id: str, message: str, channel: str = "email") -> ResolutionState:
    return ResolutionState(
        ticket_id=ticket_id,
        channel=channel,
        status=Status.RECEIVED.value,
        raw_message=message,
        guardrail_events=[],
        fact_gaps=[],
        facts={},
        pii_vault={},
        audit_sequences=[],
        model_calls=[],
        cost_usd="0",
    )


__all__ = ["ResolutionState", "Status", "initial_state"]
