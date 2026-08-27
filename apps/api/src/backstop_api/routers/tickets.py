"""Tickets, approvals and the Attack Lab.

The Attack Lab endpoint deserves a note. It runs the *real* input guardrail over
whatever text is posted and returns every finding, so a person can craft a hostile
message and watch each layer fire. It deliberately stops there: it never submits
the ticket, never reaches a model, and never touches a tool. A page whose whole
purpose is to be fed hostile input should not also be a way to run it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, Field

from backstop_api.service import TicketService

router = APIRouter(tags=["tickets"])


def _service(request: Request) -> TicketService:
    service: TicketService | None = getattr(request.app.state, "tickets", None)
    if service is None:  # pragma: no cover - only on a wiring mistake
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the ticket service is not available",
        )
    return service


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SubmitTicket(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    channel: Literal["email", "console", "public_webhook"] = "email"


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=1000)


class LabRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


@router.post("/tickets", status_code=status.HTTP_201_CREATED, summary="Submit a ticket")
async def submit(request: Request, body: SubmitTicket) -> dict[str, Any]:
    return await _service(request).submit(message=body.message, channel=body.channel)


@router.get("/tickets", summary="List tickets, newest first")
async def list_tickets(request: Request) -> dict[str, Any]:
    tickets = _service(request).summaries()
    return {
        "count": len(tickets),
        "awaiting_approval": sum(1 for t in tickets if t["awaiting_approval"]),
        "tickets": tickets,
    }


@router.get("/tickets/{ticket_id}", summary="One ticket, with its full trace")
async def get_ticket(request: Request, ticket_id: str) -> dict[str, Any]:
    detail = await _service(request).get(ticket_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    return detail


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@router.get("/approvals", summary="Cases waiting on a person")
async def approval_queue(request: Request) -> dict[str, Any]:
    queue = await _service(request).pending_approvals()
    return {"count": len(queue), "approvals": queue}


@router.post("/approvals/{ticket_id}", summary="Approve or decline")
async def resolve(request: Request, ticket_id: str, body: ApprovalDecision) -> dict[str, Any]:
    detail = await _service(request).resolve_approval(
        ticket_id, approved=body.approved, approver=body.approver, reason=body.reason
    )
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    return detail


# ---------------------------------------------------------------------------
# Attack Lab
# ---------------------------------------------------------------------------


@router.post("/lab/scan", summary="Run the input guardrail over arbitrary text")
async def lab_scan(request: Request, body: Annotated[LabRequest, Body()]) -> dict[str, Any]:
    """Analyse text without processing it.

    Returns what the guardrail plane found and what it recommends. Nothing is
    submitted, no model is called and no tool is touched - a page built to be fed
    hostile input must not also be a way to run it.
    """
    service = _service(request)
    sanitised = service.runtime.input_guard.run(body.message, ticket_id="LAB")

    return {
        "action": sanitised.verdict.action.value,
        "severity": sanitised.verdict.severity.name.lower(),
        "blocked": sanitised.verdict.blocked,
        "would_reach_a_model": not sanitised.verdict.blocked,
        "original_length": len(body.message),
        "normalised_length": len(sanitised.text),
        "safe_message": sanitised.text,
        "pii_placeholders": sorted(sanitised.vault.mapping),
        "events": [event.as_dict() for event in sanitised.verdict.events],
        # What the model would actually receive, framing and all. Seeing this is
        # most of the point: the delimiters and the "this is data" sentence are
        # the spotlighting, made visible.
        "prompt_block": sanitised.prompt_block(),
    }


__all__ = ["router"]
