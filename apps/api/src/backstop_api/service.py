"""The ticket service.

Owns the graph and the thin index the console reads. Everything durable lives in
the LangGraph checkpointer - the index here holds only what a list view needs, and
is rebuilt from the checkpointer on demand rather than being a second source of
truth that can disagree with the first.

The checkpointer is SQLite. That choice is doing real work in the demo: a ticket
that pauses for approval survives a restart of the API, which is the whole point
of checkpointing and is invisible if the state lives in memory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.types import Command

from backstop_api.settings import Settings
from backstop_graph import Runtime, Status, compile_graph, initial_state
from backstop_guardrails import InputGuardrail, turkish_name_gazetteer
from backstop_llm import build_client
from backstop_policy import PolicyEngine
from backstop_telemetry import get_logger
from backstop_toolgateway import ApprovalAuthority, StaticPolicy, ToolGateway
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

log = get_logger(__name__)

CHECKPOINT_DIR = Path(".backstop")
CHECKPOINT_FILE = CHECKPOINT_DIR / "tickets.sqlite"


@dataclass(slots=True)
class TicketSummary:
    """What a list view needs. Never the source of truth for anything."""

    ticket_id: str
    channel: str
    status: str
    received_at: datetime
    intent: str | None = None
    order_id: str | None = None
    amount_eur: str | None = None
    awaiting_approval: bool = False
    deliberated: bool = False
    cost_usd: str = "0"
    guardrail_flags: int = 0
    preview: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "channel": self.channel,
            "status": self.status,
            "received_at": self.received_at.isoformat(),
            "intent": self.intent,
            "order_id": self.order_id,
            "amount_eur": self.amount_eur,
            "awaiting_approval": self.awaiting_approval,
            "deliberated": self.deliberated,
            "cost_usd": self.cost_usd,
            "guardrail_flags": self.guardrail_flags,
            "preview": self.preview,
        }


class TicketService:
    """Submit tickets, read them back, and answer approval requests."""

    def __init__(self, *, runtime: Runtime, graph: Any, checkpointer: Any) -> None:
        self._runtime = runtime
        self._graph = graph
        self._checkpointer = checkpointer
        self._index: dict[str, TicketSummary] = {}

    # -- lifecycle --------------------------------------------------------

    @classmethod
    async def create(cls, settings: Settings, stack: Any) -> TicketService:
        """Build the service and register its teardown on an exit stack."""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # One synchronous mkdir at startup, before the service accepts traffic.
        # Reaching for an async filesystem wrapper here would add a dependency to
        # avoid blocking an event loop that has nothing else to do yet.
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_FILE))
        )

        ceiling = Decimal(str(settings.governance.max_auto_refund_eur))
        approvals = ApprovalAuthority(settings.jwt_secret.get_secret_value().ljust(16, "x"))

        llm = build_client(budget_usd=Decimal(str(settings.governance.daily_budget_usd)))

        runtime = Runtime(
            gateway=ToolGateway(
                registry=DEFAULT_REGISTRY,
                handlers=await _handlers(),
                approvals=approvals,
                policy=StaticPolicy(ceiling=ceiling, kill_switch=settings.governance.kill_switch),
            ),
            llm=llm,
            policy=PolicyEngine(),
            input_guard=InputGuardrail(known_names=turkish_name_gazetteer()),
            approvals=approvals,
            auto_approve_ceiling=ceiling,
            room=_room(llm),
        )

        log.info(
            "ticket_service.ready",
            provider=next(iter(llm._providers)),
            ceiling=str(ceiling),
            checkpoint=str(CHECKPOINT_FILE),
        )
        return cls(
            runtime=runtime,
            graph=compile_graph(runtime, checkpointer=checkpointer),
            checkpointer=checkpointer,
        )

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    # -- tickets ----------------------------------------------------------

    async def submit(self, *, message: str, channel: str = "email") -> dict[str, Any]:
        ticket_id = f"TCK-{uuid.uuid4().hex[:10].upper()}"
        received = datetime.now(UTC)

        self._index[ticket_id] = TicketSummary(
            ticket_id=ticket_id,
            channel=channel,
            status=Status.RECEIVED.value,
            received_at=received,
            preview=message[:140],
        )

        try:
            final = await self._graph.ainvoke(
                initial_state(ticket_id=ticket_id, message=message, channel=channel),
                self._config(ticket_id),
            )
        except Exception as exc:  # noqa: BLE001 - a mid-run failure is a state
            # The customer's message has been accepted and checkpointed. Losing it
            # because a provider was down would be the wrong failure mode for a
            # system whose entire premise is that a ticket survives interruption.
            #
            # So the ticket is marked failed with a reason, the checkpoint stays
            # where it stopped, and resuming picks up from that node. The caller
            # gets a ticket it can look at rather than a stack trace.
            log.warning("ticket.failed", ticket_id=ticket_id, error=f"{type(exc).__name__}: {exc}")
            state = await self._graph.aget_state(self._config(ticket_id))
            final = {
                **dict(state.values or {}),
                "status": Status.FAILED.value,
                "failure": f"{type(exc).__name__}: {exc}",
            }

        self._reindex(ticket_id, final, received=received, preview=message[:140])
        return self._detail(ticket_id, final)

    async def get(self, ticket_id: str) -> dict[str, Any] | None:
        state = await self._graph.aget_state(self._config(ticket_id))
        if not state.values:
            return None

        values = dict(state.values)
        if state.tasks:
            interrupts = [
                interrupt.value for task in state.tasks for interrupt in (task.interrupts or ())
            ]
            if interrupts:
                values["__interrupt__"] = interrupts
        return self._detail(ticket_id, values)

    def summaries(self) -> list[dict[str, Any]]:
        return [
            summary.as_dict()
            for summary in sorted(
                self._index.values(), key=lambda item: item.received_at, reverse=True
            )
        ]

    # -- approvals --------------------------------------------------------

    async def pending_approvals(self) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for ticket_id, summary in self._index.items():
            if not summary.awaiting_approval:
                continue
            detail = await self.get(ticket_id)
            if detail and detail.get("approval_request"):
                queue.append(
                    {
                        "ticket_id": ticket_id,
                        "received_at": summary.received_at.isoformat(),
                        "preview": summary.preview,
                        "request": detail["approval_request"],
                    }
                )
        return queue

    async def resolve_approval(
        self, ticket_id: str, *, approved: bool, approver: str, reason: str = ""
    ) -> dict[str, Any] | None:
        if ticket_id not in self._index:
            return None

        final = await self._graph.ainvoke(
            Command(resume={"approved": approved, "approver": approver, "reason": reason}),
            self._config(ticket_id),
        )
        summary = self._index[ticket_id]
        self._reindex(ticket_id, final, received=summary.received_at, preview=summary.preview)
        return self._detail(ticket_id, final)

    # -- internals --------------------------------------------------------

    @staticmethod
    def _config(ticket_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": ticket_id}}

    def _reindex(
        self, ticket_id: str, values: dict[str, Any], *, received: datetime, preview: str
    ) -> None:
        assessment = values.get("assessment") or {}
        awaiting = (
            "__interrupt__" in values or values.get("status") == Status.AWAITING_APPROVAL.value
        )

        self._index[ticket_id] = TicketSummary(
            ticket_id=ticket_id,
            channel=values.get("channel", "email"),
            status=values.get("status", Status.RECEIVED.value),
            received_at=received,
            intent=values.get("intent"),
            order_id=values.get("order_id"),
            amount_eur=assessment.get("amount_eur"),
            awaiting_approval=awaiting,
            deliberated=bool((values.get("deliberation") or {}).get("skipped") is False),
            cost_usd=values.get("cost_usd", "0"),
            guardrail_flags=len(values.get("guardrail_events", [])),
            preview=preview,
        )

    def _detail(self, ticket_id: str, values: dict[str, Any]) -> dict[str, Any]:
        interrupts = values.get("__interrupt__") or []
        request = None
        if interrupts:
            first = interrupts[0]
            request = getattr(first, "value", first)

        audit = [
            {
                "sequence": entry.sequence,
                "at": entry.at.isoformat(),
                "principal": entry.principal,
                "tool": entry.tool,
                "outcome": entry.outcome.value,
                "refusal_code": entry.refusal_code,
                "duration_ms": entry.duration_ms,
            }
            for entry in self._runtime.gateway.audit.for_ticket(ticket_id)
        ]

        return {
            "ticket_id": ticket_id,
            "status": values.get("status"),
            "channel": values.get("channel"),
            "raw_message": values.get("raw_message"),
            "safe_message": values.get("safe_message"),
            "intent": values.get("intent"),
            "order_id": values.get("order_id"),
            "customer_id": values.get("customer_id"),
            "guardrail_events": values.get("guardrail_events", []),
            "policy_refs": values.get("policy_refs", []),
            "assessment": values.get("assessment"),
            "policy_decision": values.get("policy_decision"),
            "deliberation": values.get("deliberation"),
            "approval_request": request or values.get("approval_request"),
            "approval": values.get("approval"),
            "execution": values.get("execution"),
            "reply": values.get("released_reply"),
            "fact_gaps": values.get("fact_gaps", []),
            "model_calls": values.get("model_calls", []),
            "cost_usd": values.get("cost_usd", "0"),
            "failure": values.get("failure"),
            "audit": audit,
            "pii_placeholders": sorted(values.get("pii_vault", {})),
        }


async def _handlers() -> dict[str, Any]:
    from backstop_mcp.bridge import local_handlers

    return dict(await local_handlers())


def _room(llm: Any) -> Any:
    """The deliberation room, when the package is installed.

    Optional so the API still starts in a deployment that ships without it. The
    graph reports the degradation rather than hiding it.
    """
    try:
        from backstop_deliberation import DeliberationRoom
    except ImportError:  # pragma: no cover - only in a trimmed deployment
        return None
    return DeliberationRoom(llm, max_messages=6)


__all__ = ["CHECKPOINT_FILE", "TicketService", "TicketSummary"]
