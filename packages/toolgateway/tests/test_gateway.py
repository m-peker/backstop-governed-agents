"""The capability boundary.

These are the tests that decide whether the security story in the README is true
or decorative. They are written against behaviour a reviewer would care about -
"a persuaded agent still cannot refund twice" - rather than against internals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from backstop_toolgateway import (
    ApprovalAuthority,
    ApprovalInvalid,
    ApprovalRequired,
    AuditChain,
    FixedClock,
    KillSwitchEngaged,
    MemoryIdempotencyStore,
    Outcome,
    Principal,
    RateLimited,
    RateLimiter,
    Scope,
    ScopeDenied,
    StaticPolicy,
    ToolExecutionFailed,
    ToolGateway,
    UnknownTool,
)
from backstop_toolgateway.principal import (
    DELIBERATION_FRAUD_INVESTIGATOR,
    GRAPH_EXECUTOR,
    GRAPH_INVESTIGATOR,
)
from backstop_toolgateway.scopes import DEFAULT_REGISTRY

SECRET = "test-secret-at-least-16-chars"
TICKET = "TCK-1001"
START = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class RefundLedger:
    """Stands in for the payments server, and counts how often it was actually hit."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def issue_refund(self, args: Any) -> dict[str, Any]:
        self.calls.append(dict(args))
        return {"refund_id": f"REF-{len(self.calls):04d}", "amount_eur": args["amount_eur"]}


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def ledger() -> RefundLedger:
    return RefundLedger()


@pytest.fixture
def approvals(clock: FixedClock) -> ApprovalAuthority:
    return ApprovalAuthority(SECRET, clock=clock)


def build_gateway(
    clock: FixedClock,
    approvals: ApprovalAuthority,
    ledger: RefundLedger,
    *,
    ceiling: str = "75.00",
    kill_switch: bool = False,
) -> ToolGateway:
    async def get_order(args: Any) -> dict[str, Any]:
        return {"order_id": args["order_id"], "total_eur": "120.00"}

    async def boom(_: Any) -> dict[str, Any]:
        raise RuntimeError("upstream exploded with secret=hunter2")

    return ToolGateway(
        registry=DEFAULT_REGISTRY,
        handlers={
            "get_order": get_order,
            "issue_refund": ledger.issue_refund,
            "issue_store_credit": boom,
            "create_replacement_order": ledger.issue_refund,
        },
        approvals=approvals,
        policy=StaticPolicy(ceiling=Decimal(ceiling), kill_switch=kill_switch),
        audit=AuditChain(clock=clock),
        idempotency=MemoryIdempotencyStore(clock=clock),
        rate_limiter=RateLimiter(clock=clock),
        clock=clock,
    )


@pytest.fixture
def gateway(clock: FixedClock, approvals: ApprovalAuthority, ledger: RefundLedger) -> ToolGateway:
    return build_gateway(clock, approvals, ledger)


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------


async def test_read_only_principal_cannot_move_money(gateway: ToolGateway) -> None:
    with pytest.raises(ScopeDenied) as caught:
        await gateway.invoke(
            principal=GRAPH_INVESTIGATOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "10.00"},
        )

    assert caught.value.required == "payments:write"
    assert "payments:write" not in caught.value.held


async def test_every_deliberation_role_is_read_only() -> None:
    from backstop_toolgateway.principal import ALL_PRINCIPALS

    for principal in ALL_PRINCIPALS:
        if principal.id.startswith("deliberation:"):
            assert principal.is_read_only, f"{principal.id} can write"


async def test_scope_is_narrow_not_merely_absent(gateway: ToolGateway) -> None:
    """The fraud investigator reads orders and shipping, and nothing else."""
    with pytest.raises(ScopeDenied):
        await gateway.invoke(
            principal=DELIBERATION_FRAUD_INVESTIGATOR,
            ticket_id=TICKET,
            tool="search_policy",
            args={"query": "return window"},
        )


async def test_available_tools_reflects_scopes(gateway: ToolGateway) -> None:
    names = {spec.name for spec in gateway.available_tools(GRAPH_INVESTIGATOR)}

    assert "get_order" in names
    assert "issue_refund" not in names


async def test_unknown_tool_is_refused_and_audited(gateway: ToolGateway) -> None:
    with pytest.raises(UnknownTool):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="drop_all_tables", args={}
        )

    entry = gateway.audit.entries[-1]
    assert entry.outcome is Outcome.REFUSED
    assert entry.refusal_code == "unknown_tool"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


async def test_kill_switch_refuses_writes_before_any_other_check(
    clock: FixedClock, approvals: ApprovalAuthority, ledger: RefundLedger
) -> None:
    gateway = build_gateway(clock, approvals, ledger, kill_switch=True)

    # A principal that holds the scope, an amount under the ceiling, valid
    # arguments. Everything else would pass. The kill switch still refuses.
    with pytest.raises(KillSwitchEngaged):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "10.00"},
        )

    assert ledger.calls == []


async def test_kill_switch_leaves_reads_working(
    clock: FixedClock, approvals: ApprovalAuthority, ledger: RefundLedger
) -> None:
    gateway = build_gateway(clock, approvals, ledger, kill_switch=True)

    result = await gateway.invoke(
        principal=GRAPH_INVESTIGATOR,
        ticket_id=TICKET,
        tool="get_order",
        args={"order_id": "ORD-0000001"},
    )

    assert result.value["order_id"] == "ORD-0000001"


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


async def test_amount_under_ceiling_needs_no_approval(
    gateway: ToolGateway, ledger: RefundLedger
) -> None:
    result = await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": "ORD-0000001", "amount_eur": "74.99"},
    )

    assert result.replayed is False
    assert len(ledger.calls) == 1


async def test_amount_over_ceiling_requires_approval(
    gateway: ToolGateway, ledger: RefundLedger
) -> None:
    with pytest.raises(ApprovalRequired) as caught:
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "75.01"},
        )

    assert caught.value.amount == Decimal("75.01")
    assert caught.value.ceiling == Decimal("75.00")
    assert ledger.calls == []


async def test_valid_approval_lets_a_large_refund_through(
    gateway: ToolGateway, approvals: ApprovalAuthority, ledger: RefundLedger
) -> None:
    args = {"order_id": "ORD-0000001", "amount_eur": "500.00"}
    token = approvals.issue(
        ticket_id=TICKET,
        tool="issue_refund",
        args=args,
        approver="ops.supervisor",
        max_amount=Decimal("500.00"),
    )

    result = await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args=args,
        approval=token,
    )

    assert len(ledger.calls) == 1
    entry = gateway.audit.entries[result.audit_sequence]
    assert entry.approval is not None
    assert entry.approval["approver"] == "ops.supervisor"


async def test_approval_cannot_be_replayed_against_a_different_ticket(
    gateway: ToolGateway, approvals: ApprovalAuthority, ledger: RefundLedger
) -> None:
    args = {"order_id": "ORD-0000001", "amount_eur": "500.00"}
    token = approvals.issue(
        ticket_id=TICKET, tool="issue_refund", args=args, approver="ops.supervisor"
    )

    with pytest.raises(ApprovalInvalid, match="bound to ticket"):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id="TCK-9999",
            tool="issue_refund",
            args=args,
            approval=token,
        )

    assert ledger.calls == []


async def test_approval_does_not_survive_a_change_of_arguments(
    gateway: ToolGateway, approvals: ApprovalAuthority, ledger: RefundLedger
) -> None:
    """The attack this exists to stop: approve 20, execute 2,000."""
    approved = {"order_id": "ORD-0000001", "amount_eur": "20.00"}
    token = approvals.issue(
        ticket_id=TICKET, tool="issue_refund", args=approved, approver="ops.supervisor"
    )

    with pytest.raises(ApprovalInvalid, match="arguments changed"):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "2000.00"},
            approval=token,
        )

    assert ledger.calls == []


async def test_approval_respects_its_own_amount_ceiling(
    gateway: ToolGateway, approvals: ApprovalAuthority
) -> None:
    args = {"order_id": "ORD-0000001", "amount_eur": "300.00"}
    token = approvals.issue(
        ticket_id=TICKET,
        tool="issue_refund",
        args=args,
        approver="ops.supervisor",
        max_amount=Decimal("100.00"),
    )

    with pytest.raises(ApprovalInvalid, match="covers up to"):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args=args,
            approval=token,
        )


async def test_approval_expires(
    gateway: ToolGateway, approvals: ApprovalAuthority, clock: FixedClock
) -> None:
    args = {"order_id": "ORD-0000001", "amount_eur": "500.00"}
    token = approvals.issue(
        ticket_id=TICKET, tool="issue_refund", args=args, approver="ops.supervisor"
    )

    clock.advance(31 * 60)

    with pytest.raises(ApprovalInvalid, match="expired"):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args=args,
            approval=token,
        )


async def test_forged_approval_is_rejected(gateway: ToolGateway, clock: FixedClock) -> None:
    """A token minted with the wrong secret does not verify."""
    forger = ApprovalAuthority("attacker-secret-16-chars", clock=clock)
    args = {"order_id": "ORD-0000001", "amount_eur": "5000.00"}
    token = forger.issue(
        ticket_id=TICKET, tool="issue_refund", args=args, approver="ops.supervisor"
    )

    with pytest.raises(ApprovalInvalid, match="signature"):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args=args,
            approval=token,
        )


async def test_replacement_always_needs_a_human_regardless_of_amount(
    gateway: ToolGateway,
) -> None:
    with pytest.raises(ApprovalRequired):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="create_replacement_order",
            args={"order_id": "ORD-0000001", "sku": "SKU-APP-0001"},
        )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_a_replayed_refund_executes_once(gateway: ToolGateway, ledger: RefundLedger) -> None:
    """The crash-and-resume case. The graph calls twice; the customer is paid once."""
    args = {"order_id": "ORD-0000001", "amount_eur": "40.00"}

    first = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args
    )
    second = await gateway.invoke(
        principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args
    )

    assert len(ledger.calls) == 1
    assert first.replayed is False
    assert second.replayed is True
    assert second.value == first.value


async def test_the_replay_is_visible_in_the_audit_chain(
    gateway: ToolGateway,
) -> None:
    args = {"order_id": "ORD-0000001", "amount_eur": "40.00"}
    await gateway.invoke(principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args)
    await gateway.invoke(principal=GRAPH_EXECUTOR, ticket_id=TICKET, tool="issue_refund", args=args)

    outcomes = [entry.outcome for entry in gateway.audit.for_ticket(TICKET)]
    assert outcomes == [Outcome.ALLOWED, Outcome.REPLAYED]


async def test_a_genuinely_different_refund_is_not_swallowed(
    gateway: ToolGateway, ledger: RefundLedger
) -> None:
    await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": "ORD-0000001", "amount_eur": "40.00"},
    )
    await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": "ORD-0000002", "amount_eur": "40.00"},
    )

    assert len(ledger.calls) == 2


async def test_reads_are_not_deduplicated(gateway: ToolGateway) -> None:
    """A read must reflect current state, so replay would be wrong."""
    args = {"order_id": "ORD-0000001"}

    first = await gateway.invoke(
        principal=GRAPH_INVESTIGATOR, ticket_id=TICKET, tool="get_order", args=args
    )
    second = await gateway.invoke(
        principal=GRAPH_INVESTIGATOR, ticket_id=TICKET, tool="get_order", args=args
    )

    assert first.replayed is False
    assert second.replayed is False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_sustained_calls_are_limited(gateway: ToolGateway) -> None:
    # issue_refund allows 10 per minute and the bucket starts full.
    for index in range(10):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": f"ORD-000{index:04d}", "amount_eur": "5.00"},
        )

    with pytest.raises(RateLimited) as caught:
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0009999", "amount_eur": "5.00"},
        )

    assert caught.value.retry_after_seconds > 0
    assert caught.value.retryable is True


async def test_the_bucket_refills(gateway: ToolGateway, clock: FixedClock) -> None:
    for index in range(10):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": f"ORD-000{index:04d}", "amount_eur": "5.00"},
        )

    clock.advance(30)

    result = await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": "ORD-0009999", "amount_eur": "5.00"},
    )
    assert result.replayed is False


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


async def test_handler_failure_does_not_leak_upstream_detail_to_the_caller(
    gateway: ToolGateway,
) -> None:
    with pytest.raises(ToolExecutionFailed) as caught:
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_store_credit",
            args={"customer_id": "CUS-00001", "amount_eur": "10.00"},
        )

    assert "hunter2" not in str(caught.value)
    # The operator can still see it, in the audit entry.
    assert "hunter2" in gateway.audit.entries[-1].detail


async def test_a_failed_write_is_not_cached_as_a_success(
    gateway: ToolGateway,
) -> None:
    args = {"customer_id": "CUS-00001", "amount_eur": "10.00"}

    for _ in range(2):
        with pytest.raises(ToolExecutionFailed):
            await gateway.invoke(
                principal=GRAPH_EXECUTOR,
                ticket_id=TICKET,
                tool="issue_store_credit",
                args=args,
            )

    outcomes = [entry.outcome for entry in gateway.audit.for_ticket(TICKET)]
    assert outcomes == [Outcome.FAILED, Outcome.FAILED]


# ---------------------------------------------------------------------------
# Audit chain
# ---------------------------------------------------------------------------


async def test_the_chain_verifies_after_a_mixed_run(
    gateway: ToolGateway, approvals: ApprovalAuthority
) -> None:
    await gateway.invoke(
        principal=GRAPH_INVESTIGATOR,
        ticket_id=TICKET,
        tool="get_order",
        args={"order_id": "ORD-0000001"},
    )
    with pytest.raises(ScopeDenied):
        await gateway.invoke(
            principal=GRAPH_INVESTIGATOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "10.00"},
        )
    await gateway.invoke(
        principal=GRAPH_EXECUTOR,
        ticket_id=TICKET,
        tool="issue_refund",
        args={"order_id": "ORD-0000001", "amount_eur": "10.00"},
    )

    gateway.audit.verify()
    assert len(gateway.audit) == 3


async def test_editing_a_past_entry_breaks_the_chain(gateway: ToolGateway) -> None:
    for index in range(3):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": f"ORD-000{index:04d}", "amount_eur": "10.00"},
        )

    chain = gateway.audit
    chain.verify()

    # Someone with database access quietly lowers a recorded refund.
    tampered = chain.entries[1].model_copy(update={"amount": Decimal("1.00")})
    chain._entries[1] = tampered

    with pytest.raises(ValueError, match="entry 1 has been modified"):
        chain.verify()


async def test_deleting_an_entry_breaks_the_chain(gateway: ToolGateway) -> None:
    for index in range(3):
        await gateway.invoke(
            principal=GRAPH_EXECUTOR,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": f"ORD-000{index:04d}", "amount_eur": "10.00"},
        )

    chain = gateway.audit
    del chain._entries[1]

    with pytest.raises(ValueError):
        chain.verify()


async def test_audit_records_the_argument_digest_not_the_arguments(
    gateway: ToolGateway,
) -> None:
    await gateway.invoke(
        principal=GRAPH_INVESTIGATOR,
        ticket_id=TICKET,
        tool="get_order",
        args={"order_id": "ORD-0000001"},
    )

    entry = gateway.audit.entries[-1]
    assert len(entry.args_digest) == 64
    assert "ORD-0000001" not in entry.model_dump_json()


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_a_handler_for_an_undeclared_tool_is_a_wiring_error(
    approvals: ApprovalAuthority,
) -> None:
    async def rogue(_: Any) -> None:
        return None

    with pytest.raises(ValueError, match="undeclared tools"):
        ToolGateway(registry=DEFAULT_REGISTRY, handlers={"exfiltrate": rogue}, approvals=approvals)


def test_every_write_tool_declares_how_it_is_gated() -> None:
    """A write tool with neither an amount nor a mandatory approval is a hole."""
    for spec in DEFAULT_REGISTRY.write_tools():
        assert spec.amount_argument or spec.always_requires_approval, spec.name
        assert spec.scope is Scope.PAYMENTS_WRITE


async def test_an_unparseable_amount_never_bypasses_the_ceiling(
    gateway: ToolGateway, ledger: RefundLedger
) -> None:
    """A junk amount must fail, not be read as "no amount" and skip the ceiling."""
    principal = Principal(
        id="test:executor", label="test", scopes=frozenset({Scope.PAYMENTS_WRITE})
    )

    with pytest.raises(ToolExecutionFailed, match="not a valid amount"):
        await gateway.invoke(
            principal=principal,
            ticket_id=TICKET,
            tool="issue_refund",
            args={"order_id": "ORD-0000001", "amount_eur": "one thousand"},
        )

    assert ledger.calls == []
    # And the refusal left a trace: an unaudited refusal is a gap in the record.
    assert gateway.audit.entries[-1].refusal_code == "tool_execution_failed"
    gateway.audit.verify()
