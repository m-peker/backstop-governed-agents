"""The governance view.

Answers one question in one request: what is this system allowed to do, what has
it actually done, and does the record still verify.

Everything here is derived from the audit chain and the registries rather than
from a separate metrics store. A governance dashboard fed by its own counters can
disagree with the record it claims to summarise, and the moment it does, neither
number is worth anything.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backstop_api.deps.common import SettingsDep
from backstop_api.service import TicketService

router = APIRouter(prefix="/governance", tags=["governance"])


def _service(request: Request) -> TicketService:
    service: TicketService | None = getattr(request.app.state, "tickets", None)
    if service is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="the ticket service is not available")
    return service


@router.get("/overview", summary="Controls in force, activity, and chain integrity")
async def overview(request: Request, settings: SettingsDep) -> dict[str, Any]:
    service = _service(request)
    chain = service.runtime.gateway.audit
    tickets = service.summaries()

    outcomes = Counter(entry.outcome.value for entry in chain)
    refusals = Counter(entry.refusal_code for entry in chain if entry.refusal_code is not None)
    tools = Counter(entry.tool for entry in chain)

    try:
        chain.verify()
        integrity: dict[str, Any] = {"verified": True, "problem": None}
    except ValueError as broken:
        integrity = {"verified": False, "problem": str(broken)}

    ledger = service.runtime.llm.ledger
    budget = service.runtime.llm.budget

    return {
        "controls": {
            "environment": settings.env,
            "kill_switch_engaged": settings.governance.kill_switch,
            "auto_approve_ceiling_eur": settings.governance.max_auto_refund_eur,
            "daily_budget_usd": settings.governance.daily_budget_usd,
            "pii_detokenize_channels": list(settings.governance.pii_detokenize_channels),
        },
        "spend": {
            "total_usd": str(ledger.total),
            "by_task": ledger.breakdown(),
            "budget_usd": str(budget.ceiling) if budget.ceiling is not None else None,
            "remaining_usd": str(budget.remaining) if budget.remaining is not None else None,
            "circuit_breaker_tripped": budget.exhausted,
        },
        "tickets": {
            "total": len(tickets),
            "by_status": dict(Counter(ticket["status"] for ticket in tickets)),
            "awaiting_approval": sum(1 for t in tickets if t["awaiting_approval"]),
            "deliberated": sum(1 for t in tickets if t["deliberated"]),
        },
        "capability_use": {
            "entries": len(chain),
            "by_outcome": dict(outcomes),
            "refusals": dict(refusals),
            "top_tools": dict(tools.most_common(8)),
        },
        # Recomputed on every request rather than cached. A cached "verified"
        # is a claim about the past.
        "audit_chain": {**integrity, "head": chain.head},
    }


@router.get("/prompts", summary="Registered prompts and their content hashes")
async def prompts() -> dict[str, Any]:
    from backstop_graph import prompts as registry

    return {
        "prompts": [
            {
                "name": prompt.name,
                "version": prompt.version,
                "reference": prompt.reference,
                "owner": prompt.owner,
                "changelog": prompt.changelog,
                "hash": prompt.hash,
            }
            for prompt in sorted(registry.registry(), key=lambda p: p.reference)
        ]
    }


@router.get("/rules", summary="The policy rules and the clauses each implements")
async def rules() -> dict[str, Any]:
    from backstop_policy import ALL_RULES

    return {
        "count": len(ALL_RULES),
        "rules": [
            {
                "id": rule.id,
                "description": rule.description,
                "clauses": list(rule.clauses),
            }
            for rule in ALL_RULES
        ],
    }


@router.get("/audit/{ticket_id}", summary="Every capability use on one ticket")
async def audit_for_ticket(request: Request, ticket_id: str) -> dict[str, Any]:
    chain = _service(request).runtime.gateway.audit
    entries = chain.for_ticket(ticket_id)

    if not entries:
        raise HTTPException(status_code=404, detail=f"no audit entries for {ticket_id}")

    return {
        "ticket_id": ticket_id,
        "entries": [
            {
                "sequence": entry.sequence,
                "at": entry.at.isoformat(),
                "principal": entry.principal,
                "tool": entry.tool,
                "scope": entry.scope,
                "outcome": entry.outcome.value,
                "args_digest": entry.args_digest,
                "amount": str(entry.amount) if entry.amount is not None else None,
                "approval": entry.approval,
                "refusal_code": entry.refusal_code,
                "detail": entry.detail,
                "duration_ms": entry.duration_ms,
                "entry_hash": entry.entry_hash,
                "previous_hash": entry.previous_hash,
            }
            for entry in entries
        ],
        "total_moved_eur": str(
            sum(
                (entry.amount or Decimal("0"))
                for entry in entries
                if entry.outcome.value == "allowed" and entry.amount is not None
            )
        ),
    }


__all__ = ["router"]
