"""The nodes.

Each is an async function taking the state and returning the fields it changed.
None of them mutates the state in place - LangGraph merges the returned dict, and
returning a partial keeps it obvious which node owns which field.

Two conventions worth stating.

**A node never raises for an expected outcome.** A refused refund, a missing fact,
a blocked reply: all of these are states, and they are returned as states. An
exception here would lose the checkpoint and with it the reason.

**A node never decides what it is permitted to do.** Permission lives in the tool
gateway and the policy engine. The nodes ask, and route on the answer.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any

from langgraph.types import interrupt

from backstop_graph import prompts
from backstop_graph.runtime import Runtime
from backstop_graph.schemas import Assessment, Classification, ReplyDraft
from backstop_graph.state import ResolutionState, Status
from backstop_guardrails import (
    Action,
    GuardrailVerdict,
    OutputCandidate,
    OutputGuardrail,
    Provenance,
    SanitisedInput,
    Spotlight,
    Vault,
)
from backstop_llm import TaskClass
from backstop_policy import (
    CustomerTier,
    EvidenceStrength,
    Intent,
    PolicyContext,
    Resolution,
)
from backstop_toolgateway import ApprovalRequired, GatewayError
from backstop_toolgateway.principal import (
    GRAPH_EXECUTOR,
    GRAPH_INVESTIGATOR,
    GRAPH_POLICY_READER,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rehydrate(state: ResolutionState) -> SanitisedInput:
    """Rebuild the guardrail context from checkpointed primitives.

    The state stores the vault as a plain mapping so it survives a round trip
    through the checkpointer; the output guardrail wants the object. Cheap to
    rebuild, and it keeps the serialisation constraint in one place.
    """
    vault = Vault(ticket_id=state["ticket_id"])
    vault.mapping.update(state.get("pii_vault", {}))

    return SanitisedInput(
        text=state.get("safe_message", ""),
        original=state.get("raw_message", ""),
        vault=vault,
        spotlight=Spotlight(marker=state.get("spotlight_marker", "")),
        canary=state.get("canary", ""),
        # The verdict is not rebuilt: the input findings already live in
        # state["guardrail_events"] and rehydrating them here would double-count
        # them in the output pass.
        verdict=GuardrailVerdict(events=()),
    )


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _record_call(completion: Any, prompt: prompts.Prompt) -> dict[str, Any]:
    return {**completion.as_audit_fields(), **prompt.as_audit_fields()}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def make_nodes(runtime: Runtime) -> dict[str, Any]:
    """Build every node, closed over the runtime."""

    # -- 1. guardrail_in ---------------------------------------------------

    async def guardrail_in(state: ResolutionState) -> ResolutionState:
        sanitised = runtime.input_guard.run(state["raw_message"], ticket_id=state["ticket_id"])

        blocked = sanitised.verdict.blocked
        return ResolutionState(
            safe_message=sanitised.text,
            pii_vault=dict(sanitised.vault.mapping),
            spotlight_marker=sanitised.spotlight.marker,
            canary=sanitised.canary,
            guardrail_events=[event.as_dict() for event in sanitised.verdict.events],
            status=(Status.BLOCKED if blocked else Status.IN_PROGRESS).value,
            failure=(
                "input guardrail refused the message: " + "; ".join(sanitised.verdict.reasons())
                if blocked
                else None
            ),
        )

    # -- 2. classify -------------------------------------------------------

    async def classify(state: ResolutionState) -> ResolutionState:
        sanitised = _rehydrate(state)
        prompt = prompts.CLASSIFY

        completion = await runtime.llm.complete(
            task=TaskClass.CLASSIFY,
            system=prompt.render(canary=state["canary"]),
            user=sanitised.prompt_block(source=Provenance.CUSTOMER),
            schema=Classification,
        )
        result = completion.value

        return ResolutionState(
            intent=result.intent.value,
            intent_confidence=result.confidence,
            order_id=result.order_id,
            assessment={"summary": result.summary, "requests_human": result.requests_human},
            model_calls=[_record_call(completion, prompt)],
            cost_usd=str(runtime.llm.ledger.total),
        )

    # -- 3. gather_facts ---------------------------------------------------

    async def gather_facts(state: ResolutionState) -> ResolutionState:
        """Fan out to the tool plane.

        Concurrency lives inside this node rather than in a LangGraph fan-out.
        The tools are independent reads with no branching between them, so a
        single node with ``asyncio.gather`` gets the same wall-clock behaviour
        while keeping the state merge trivial and the trace readable.

        A tool that fails does not fail the ticket. It records a gap, and the
        assessment step is told what it is missing - which is how a decision
        degrades honestly instead of being made on half the facts without saying so.
        """
        order_id = state.get("order_id")
        if not order_id:
            return ResolutionState(fact_gaps=["no order reference was quoted in the message"])

        ticket = state["ticket_id"]

        async def call(tool: str, **args: Any) -> tuple[str, Any, str | None]:
            try:
                result = await runtime.gateway.invoke(
                    principal=GRAPH_INVESTIGATOR, ticket_id=ticket, tool=tool, args=args
                )
            except GatewayError as refusal:
                return tool, None, f"{tool}: {refusal}"
            return tool, result.value, None

        order_result = await call("get_order", order_id=order_id)
        facts: dict[str, Any] = {}
        gaps: list[str] = []

        if order_result[1] is None:
            return ResolutionState(fact_gaps=[order_result[2] or "order not found"])

        facts["order"] = order_result[1]
        customer_id = order_result[1]["customer_id"]
        first_sku = order_result[1]["lines"][0]["sku"] if order_result[1]["lines"] else None

        pending = [
            call("get_customer_profile", customer_id=customer_id),
            call("track_shipment", order_id=order_id),
            call("get_movements_for_order", order_id=order_id),
        ]
        if first_sku:
            pending.append(call("get_return_eligibility", order_id=order_id, sku=first_sku))

        for tool, value, gap in await asyncio.gather(*pending):
            if gap:
                gaps.append(gap)
            else:
                facts[tool] = value

        return ResolutionState(facts=facts, customer_id=customer_id, fact_gaps=gaps)

    # -- 4. policy_retrieval ----------------------------------------------

    async def policy_retrieval(state: ResolutionState) -> ResolutionState:
        query_parts = [
            state.get("intent", "").replace("_", " "),
            state.get("assessment", {}).get("summary", ""),
        ]
        query = " ".join(part for part in query_parts if part).strip()

        try:
            result = await runtime.gateway.invoke(
                principal=GRAPH_POLICY_READER,
                ticket_id=state["ticket_id"],
                tool="search_policy",
                args={"query": query or "return refund", "limit": 6},
            )
        except GatewayError as refusal:
            return ResolutionState(
                policy_refs=[], retrieved_clause_ids=[], fact_gaps=[f"policy search: {refusal}"]
            )

        clauses = result.value["results"]
        return ResolutionState(
            policy_refs=clauses,
            retrieved_clause_ids=[clause["clause_id"] for clause in clauses],
        )

    # -- 5. assess ---------------------------------------------------------

    async def assess(state: ResolutionState) -> ResolutionState:
        sanitised = _rehydrate(state)
        prompt = prompts.ASSESS

        clause_text = "\n".join(
            f"{clause['clause_id']} ({clause['section_title']}): {clause['text']}"
            for clause in state.get("policy_refs", [])
        )
        gaps = state.get("fact_gaps", [])

        user = "\n\n".join(
            part
            for part in (
                sanitised.prompt_block(source=Provenance.CUSTOMER),
                f"Classified intent: {state.get('intent', 'unknown')}",
                _facts_block(state),
                sanitised.spotlight.wrap(
                    clause_text, source=Provenance.RETRIEVED, label="policy clauses"
                )
                if clause_text
                else "No policy clauses were retrieved.",
                ("Facts that could not be gathered:\n- " + "\n- ".join(gaps) if gaps else ""),
            )
            if part
        )

        completion = await runtime.llm.complete(
            task=TaskClass.ASSESS,
            system=prompt.render(canary=state["canary"]),
            user=user,
            schema=Assessment,
        )
        result = completion.value

        return ResolutionState(
            assessment={
                **state.get("assessment", {}),
                "resolution": result.resolution.value,
                "amount_eur": result.amount_eur,
                "confidence": result.confidence,
                "cited_clauses": result.cited_clauses,
                "rationale": result.rationale,
                "needs_human": result.needs_human,
                "concerns": result.concerns,
            },
            model_calls=[_record_call(completion, prompt)],
            cost_usd=str(runtime.llm.ledger.total),
        )

    # -- 6. policy_gate ----------------------------------------------------

    async def policy_gate(state: ResolutionState) -> ResolutionState:
        """The deterministic re-check. The model proposed; this decides."""
        context = _policy_context(state, runtime)
        decision = runtime.policy.evaluate(context)

        assessment = state.get("assessment", {})
        low_confidence = assessment.get("confidence", 1.0) < runtime.min_confidence

        return ResolutionState(
            policy_decision={
                **decision.as_dict(),
                "low_confidence": low_confidence,
                "model_asked_for_human": bool(assessment.get("needs_human")),
            }
        )

    # -- 6b. deliberate ----------------------------------------------------

    async def deliberate(state: ResolutionState) -> ResolutionState:
        """Convene the room on a case the policy contradicts itself about.

        The verdict is recorded and carried into the approval request. It does
        **not** replace the assessment and it does not decide anything: the room is
        convened precisely because the case is hard, which makes its own confidence
        the least reliable thing about it. What it produces is a prepared case -
        both sides argued, with the dissent stated - for the person who decides.
        """
        decision = state.get("policy_decision", {})

        if runtime.room is None:
            return ResolutionState(
                deliberation={
                    "skipped": True,
                    "reason": "no deliberation room is configured; the case goes "
                    "to a human unargued",
                }
            )

        sanitised = _rehydrate(state)
        clause_text = "\n".join(
            f"{clause['clause_id']} ({clause['section_title']}): {clause['text']}"
            for clause in state.get("policy_refs", [])
        )
        assessment = state.get("assessment", {})

        brief = "\n\n".join(
            part
            for part in (
                sanitised.prompt_block(source=Provenance.CUSTOMER),
                _facts_block(state),
                sanitised.spotlight.wrap(
                    clause_text, source=Provenance.RETRIEVED, label="policy clauses"
                )
                if clause_text
                else "",
                f"The proposed resolution is {assessment.get('resolution')}.",
                "The policy engine cannot settle this case: "
                + str(decision.get("explanation", "")),
            )
            if part
        )

        record = await runtime.room.deliberate(brief=brief)
        payload = record.as_dict() if hasattr(record, "as_dict") else {"verdict": str(record)}

        return ResolutionState(
            deliberation={**payload, "skipped": False},
            cost_usd=str(runtime.llm.ledger.total),
        )

    # -- 7. human_approval -------------------------------------------------

    async def human_approval(state: ResolutionState) -> ResolutionState:
        """Pause the graph until a person answers.

        ``interrupt()`` stops execution here and persists the checkpoint. The
        request is what the console shows the reviewer; the value they send back
        is what this returns with.
        """
        assessment = state.get("assessment", {})
        decision = state.get("policy_decision", {})

        request = {
            "ticket_id": state["ticket_id"],
            "proposed_resolution": assessment.get("resolution"),
            "amount_eur": assessment.get("amount_eur"),
            "rationale": assessment.get("rationale"),
            "concerns": assessment.get("concerns", []),
            "policy_effect": decision.get("effect"),
            "policy_explanation": decision.get("explanation"),
            "clauses": decision.get("clauses", []),
            "guardrail_events": state.get("guardrail_events", []),
            # When the room sat, the reviewer sees both cases argued and the
            # dissent, rather than having to construct the counter-argument.
            "deliberation": state.get("deliberation"),
        }

        answer = interrupt(request)

        approved = bool(answer.get("approved")) if isinstance(answer, dict) else bool(answer)
        return ResolutionState(
            approval_request=request,
            approval={
                "approved": approved,
                "approver": (answer or {}).get("approver", "unknown")
                if isinstance(answer, dict)
                else "unknown",
                "reason": (answer or {}).get("reason", "") if isinstance(answer, dict) else "",
            },
            status=(Status.IN_PROGRESS if approved else Status.REJECTED).value,
        )

    # -- 8. execute --------------------------------------------------------

    async def execute(state: ResolutionState) -> ResolutionState:
        assessment = state.get("assessment", {})
        resolution = assessment.get("resolution")
        amount = assessment.get("amount_eur")
        order_id = state.get("order_id")
        approval = state.get("approval") or {}

        tool, args = _write_call(resolution, order_id, state.get("customer_id"), amount, state)
        if tool is None:
            return ResolutionState(execution=None)

        token = None
        if approval.get("approved"):
            token = runtime.approvals.issue(
                ticket_id=state["ticket_id"],
                tool=tool,
                args=args,
                approver=approval.get("approver", "unknown"),
                max_amount=_decimal(amount),
            )

        try:
            result = await runtime.gateway.invoke(
                principal=GRAPH_EXECUTOR,
                ticket_id=state["ticket_id"],
                tool=tool,
                args=args,
                approval=token,
            )
        except ApprovalRequired as refusal:
            # The gateway and the policy engine disagreed about whether a human
            # was needed. The gateway wins - it is the capability boundary - and
            # the disagreement is worth recording, because it means a rule drifted.
            return ResolutionState(
                execution=None,
                status=Status.AWAITING_APPROVAL.value,
                failure=f"gateway required an approval the graph did not obtain: {refusal}",
            )
        except GatewayError as refusal:
            return ResolutionState(
                execution=None,
                status=Status.FAILED.value,
                failure=f"execution refused: {refusal}",
            )

        return ResolutionState(
            execution={"tool": tool, "replayed": result.replayed, "result": result.value},
            audit_sequences=[result.audit_sequence],
        )

    # -- 9. compose_reply --------------------------------------------------

    async def compose_reply(state: ResolutionState) -> ResolutionState:
        sanitised = _rehydrate(state)
        prompt = prompts.COMPOSE
        assessment = state.get("assessment", {})
        decision = state.get("policy_decision", {})

        outcome = _describe_outcome(state)
        reason = decision.get("explanation") or assessment.get("rationale", "")
        user = "\n\n".join(
            (
                sanitised.prompt_block(source=Provenance.CUSTOMER),
                f"Decision: {outcome}",
                f"Reason recorded: {reason}",
            )
        )

        completion = await runtime.llm.complete(
            task=TaskClass.COMPOSE,
            system=prompt.render(canary=state["canary"]),
            user=user,
            schema=ReplyDraft,
        )

        return ResolutionState(
            reply=completion.value.reply,
            model_calls=[_record_call(completion, prompt)],
            cost_usd=str(runtime.llm.ledger.total),
        )

    # -- 10. guardrail_out -------------------------------------------------

    async def guardrail_out(state: ResolutionState) -> ResolutionState:
        sanitised = _rehydrate(state)
        assessment = state.get("assessment", {})

        guard = OutputGuardrail(
            retrieved_clause_ids=frozenset(state.get("retrieved_clause_ids", [])),
            policy_check=runtime.policy,
        )
        # The candidate describes the *effective* outcome, not the model's
        # original proposal. When the policy engine denied a refund, the reply
        # being checked explains a refusal - validating it against "full_refund"
        # would block the very message the refusal requires us to send.
        effective, effective_amount = _effective_outcome(state)

        approval = state.get("approval") or {}

        candidate = OutputCandidate(
            reply=state.get("reply") or "",
            decision=effective,
            amount=effective_amount,
            cited_clauses=tuple(assessment.get("cited_clauses", [])),
            human_approved=bool(approval.get("approved")),
        )

        verdict = guard.run(candidate, sanitised=sanitised, channel=state.get("channel", "email"))

        released: str | None = None
        if verdict.action is not Action.BLOCK:
            released = guard.release(
                candidate, sanitised=sanitised, channel=state.get("channel", "email")
            )

        return ResolutionState(
            guardrail_events=[event.as_dict() for event in verdict.events],
            released_reply=released,
            status=(
                Status.AWAITING_APPROVAL.value
                if verdict.blocked
                else state.get("status", Status.IN_PROGRESS.value)
            ),
            failure=(
                "output guardrail blocked the reply: " + "; ".join(verdict.reasons())
                if verdict.blocked
                else state.get("failure")
            ),
        )

    # -- 11. close ---------------------------------------------------------

    async def close(state: ResolutionState) -> ResolutionState:
        current = state.get("status", Status.IN_PROGRESS.value)
        if Status(current).is_terminal:
            return ResolutionState(cost_usd=str(runtime.llm.ledger.total))

        approval = state.get("approval") or {}
        if approval and not approval.get("approved"):
            final = Status.REJECTED
        elif state.get("execution") or state.get("released_reply"):
            final = Status.RESOLVED
        else:
            final = Status.AWAITING_APPROVAL

        return ResolutionState(status=final.value, cost_usd=str(runtime.llm.ledger.total))

    return {
        "guardrail_in": guardrail_in,
        "classify": classify,
        "gather_facts": gather_facts,
        "policy_retrieval": policy_retrieval,
        "assess": assess,
        "policy_gate": policy_gate,
        "deliberate": deliberate,
        "human_approval": human_approval,
        "execute": execute,
        "compose_reply": compose_reply,
        "guardrail_out": guardrail_out,
        "close": close,
    }


# ---------------------------------------------------------------------------
# Fact and context assembly
# ---------------------------------------------------------------------------


def _facts_block(state: ResolutionState) -> str:
    facts = state.get("facts", {})
    if not facts:
        return "No facts were gathered."

    order = facts.get("order", {})
    profile = facts.get("get_customer_profile", {})
    shipment = (facts.get("track_shipment") or {}).get("shipment") or {}
    eligibility = facts.get("get_return_eligibility", {})
    movements = facts.get("get_movements_for_order", {})

    lines = ["Facts from our systems:"]
    if order:
        lines.append(
            f"- Order {order.get('order_id')}: placed {order.get('placed_at')}, "
            f"status {order.get('status')}, total EUR {order.get('total')}"
        )
    if shipment:
        lines.append(
            f"- Shipment: {shipment.get('status')}, delivered {shipment.get('delivered_at')}, "
            f"evidence {shipment.get('evidence_strength')}, "
            f"signature {shipment.get('signature_captured')}, "
            f"photo {shipment.get('delivery_photo')}"
        )
    if eligibility:
        lines.append(
            f"- Return eligibility: {eligibility.get('days_since_delivery')} days since "
            f"delivery, window {eligibility.get('window_days')}, "
            f"blocking conditions {eligibility.get('blocking_conditions')}"
        )
    if profile:
        lines.append(
            f"- Customer: tier {profile.get('tier')}, {profile.get('tenure_days')} days old, "
            f"{profile.get('delivered_orders')} delivered orders, "
            f"return rate {profile.get('return_rate')}, "
            f"{profile.get('never_arrived_claims')} prior non-receipt claims, "
            f"{profile.get('accounts_at_this_address')} account(s) at this address"
        )
    if movements:
        lines.append(f"- Already refunded on this order: EUR {movements.get('total_refunded')}")

    return "\n".join(lines)


def _policy_context(state: ResolutionState, runtime: Runtime) -> PolicyContext:
    """Assemble the facts the rules read.

    Every value comes from tool output or from the assessment. Nothing is inferred
    here, because a ruling has to be reproducible from the audit trail, and an
    inference made at assembly time would be invisible in it.
    """
    facts = state.get("facts", {})
    order = facts.get("order", {})
    profile = facts.get("get_customer_profile", {})
    shipment = (facts.get("track_shipment") or {}).get("shipment") or {}
    eligibility = facts.get("get_return_eligibility", {})
    movements = facts.get("get_movements_for_order", {})
    assessment = state.get("assessment", {})

    def amount_of(value: Any, default: str = "0") -> Decimal:
        try:
            return Decimal(str(value if value is not None else default))
        except InvalidOperation:
            return Decimal(default)

    return PolicyContext(
        intent=_intent_of(state.get("intent")),
        resolution=_resolution_of(assessment.get("resolution")),
        amount=_decimal(assessment.get("amount_eur")),
        cited_clauses=tuple(assessment.get("cited_clauses", [])),
        order_total=amount_of(order.get("total")),
        already_refunded=amount_of(movements.get("total_refunded")),
        within_window=bool(eligibility.get("within_window", True)),
        days_since_delivery=eligibility.get("days_since_delivery"),
        blocking_conditions=tuple(eligibility.get("blocking_conditions", [])),
        evidence_strength=_evidence_of(shipment.get("evidence_strength")),
        tier=_tier_of(profile.get("tier")),
        tenure_days=int(profile.get("tenure_days", 365) or 365),
        return_rate=float(profile.get("return_rate", 0.0) or 0.0),
        delivered_orders=int(profile.get("delivered_orders", 0) or 0),
        never_arrived_claims=int(profile.get("never_arrived_claims", 0) or 0),
        accounts_at_address=int(profile.get("accounts_at_this_address", 1) or 1),
        customer_requested_human=bool(assessment.get("requests_human")),
        auto_approve_ceiling=runtime.auto_approve_ceiling,
        human_approved=bool((state.get("approval") or {}).get("approved")),
    )


def _intent_of(value: str | None) -> Intent:
    try:
        return Intent(value or "other")
    except ValueError:
        return Intent.OTHER


def _resolution_of(value: str | None) -> Resolution:
    try:
        return Resolution(value or "escalate")
    except ValueError:
        return Resolution.ESCALATE


def _tier_of(value: str | None) -> CustomerTier:
    try:
        return CustomerTier(value or "standard")
    except ValueError:
        return CustomerTier.STANDARD


def _evidence_of(value: str | None) -> EvidenceStrength:
    try:
        return EvidenceStrength(value or "none")
    except ValueError:
        return EvidenceStrength.NONE


def _write_call(
    resolution: str | None,
    order_id: str | None,
    customer_id: str | None,
    amount: str | None,
    state: ResolutionState,
) -> tuple[str | None, dict[str, Any]]:
    reason = (state.get("assessment", {}) or {}).get("rationale", "")[:200] or "resolution"

    if resolution in ("full_refund", "partial_refund") and order_id and amount:
        return "issue_refund", {"order_id": order_id, "amount_eur": amount, "reason": reason}
    if resolution == "store_credit" and customer_id and amount:
        return (
            "issue_store_credit",
            {"customer_id": customer_id, "amount_eur": amount, "reason": reason},
        )
    if resolution == "replacement" and order_id:
        order = (state.get("facts", {}) or {}).get("order", {})
        lines = order.get("lines") or []
        if lines:
            return (
                "create_replacement_order",
                {"order_id": order_id, "sku": lines[0]["sku"], "reason": reason},
            )
    return None, {}


def _effective_outcome(state: ResolutionState) -> tuple[str, Decimal | None]:
    """What actually happened, as opposed to what was proposed.

    The output guardrail checks the reply against this, because the reply is an
    explanation of the outcome. A denied refund produces a refusal letter, and a
    refusal letter must not be validated as though it were granting money.
    """
    assessment = state.get("assessment", {})
    decision = state.get("policy_decision", {})
    approval = state.get("approval") or {}

    if decision.get("effect") == "deny":
        return "rejected", None
    if approval and not approval.get("approved"):
        return "rejected", None
    if not state.get("execution"):
        return "escalate", None

    return (
        assessment.get("resolution", "escalate"),
        _decimal(assessment.get("amount_eur")),
    )


def _describe_outcome(state: ResolutionState) -> str:
    assessment = state.get("assessment", {})
    execution = state.get("execution")
    approval = state.get("approval") or {}

    if execution:
        return (
            f"{assessment.get('resolution')} of EUR {assessment.get('amount_eur')} "
            f"has been carried out (reference "
            f"{(execution.get('result') or {}).get('reference', 'n/a')})"
        )
    if approval and not approval.get("approved"):
        return "the request was reviewed by a person and declined"
    if state.get("status") == Status.AWAITING_APPROVAL.value:
        return "the case is with a colleague for review"
    return f"{assessment.get('resolution')} - not yet carried out"


__all__ = ["make_nodes"]
