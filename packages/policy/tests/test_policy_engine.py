"""Policy-as-code.

Every rule has a test that states the situation in the language of the policy, so
that a reader who knows the returns policy but not this codebase can check whether
the rule is right.

The planted ambiguities get particular attention. Those are the cases where the
prose does not decide, and what this engine does about that - refer, rather than
pick a reading - is the whole argument for having a policy engine at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backstop_policy import (
    ALL_RULES,
    CustomerTier,
    EvidenceStrength,
    Intent,
    PolicyContext,
    PolicyEngine,
    Resolution,
)


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


def ctx(**overrides: object) -> PolicyContext:
    """A plain, permissible claim, with fields overridden per test."""
    base: dict[str, object] = {
        "intent": Intent.DAMAGED_ON_ARRIVAL,
        "resolution": Resolution.FULL_REFUND,
        "amount": Decimal("40.00"),
        "order_total": Decimal("60.00"),
        "cited_clauses": ("RP-4.1",),
        "days_since_delivery": 1,
    }
    base.update(overrides)
    return PolicyContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The engine itself
# ---------------------------------------------------------------------------


def test_an_ordinary_claim_is_permitted(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx()).permitted


def test_every_rule_id_is_unique() -> None:
    ids = [rule.id for rule in ALL_RULES]
    assert len(ids) == len(set(ids))


def test_every_rule_names_the_clauses_it_implements() -> None:
    """A ruling that cannot cite a clause cannot be defended."""
    for rule in ALL_RULES:
        assert rule.clauses, rule.id
        assert rule.description, rule.id


def test_the_strongest_effect_wins(engine: PolicyEngine) -> None:
    decision = engine.evaluate(
        ctx(
            amount=Decimal("500.00"),
            order_total=Decimal("10.00"),
            blocking_conditions=("final_sale_item",),
            intent=Intent.CHANGED_MIND,
            cited_clauses=("RP-2.1",),
        )
    )
    assert decision.denied


def test_every_ruling_is_kept_not_just_the_decisive_one(engine: PolicyEngine) -> None:
    """A dossier should show every reason, not the first one found."""
    decision = engine.evaluate(
        ctx(
            amount=Decimal("500.00"),
            order_total=Decimal("600.00"),
            intent=Intent.NEVER_ARRIVED,
            evidence_strength=EvidenceStrength.STRONG,
            cited_clauses=("RP-5.3",),
        )
    )

    rule_ids = {ruling.rule_id for ruling in decision.rulings}
    assert {"R-CEILING", "R-EVIDENCED-DELIVERY"} <= rule_ids


def test_the_decision_explains_itself(engine: PolicyEngine) -> None:
    decision = engine.evaluate(ctx(amount=Decimal("500.00"), order_total=Decimal("600.00")))
    assert "exceeds the automatic approval ceiling" in decision.explain()
    assert "GP-3.2" in decision.clauses


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_a_refund_larger_than_the_order_is_denied(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx(amount=Decimal("100.00"), order_total=Decimal("60.00"))).denied


def test_refunds_cannot_accumulate_past_the_order_total(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(
            amount=Decimal("40.00"),
            order_total=Decimal("60.00"),
            already_refunded=Decimal("30.00"),
        )
    ).denied


def test_a_resolution_without_a_cited_clause_needs_a_person(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx(cited_clauses=())).requires_human


def test_escalating_needs_no_citation(engine: PolicyEngine) -> None:
    """Escalation is the absence of a decision, so there is nothing to ground."""
    assert engine.evaluate(
        ctx(resolution=Resolution.ESCALATE, amount=None, cited_clauses=())
    ).permitted


# ---------------------------------------------------------------------------
# Ceilings
# ---------------------------------------------------------------------------


def test_an_amount_over_the_ceiling_needs_a_person(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(amount=Decimal("75.01"), order_total=Decimal("100.00"))
    ).requires_human


def test_an_amount_at_the_ceiling_does_not(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx(amount=Decimal("75.00"), order_total=Decimal("100.00"))).permitted


def test_amb_04_discretion_does_not_create_authority(engine: PolicyEngine) -> None:
    """GP-3.3 reads as an unlimited grant. The ceiling binds anyway.

    This is the planted ambiguity that is *not* for deliberation: the answer must
    not depend on which agent argued better.
    """
    decision = engine.evaluate(
        ctx(
            resolution=Resolution.STORE_CREDIT,
            intent=Intent.LATE_DELIVERY,
            amount=Decimal("400.00"),
            order_total=Decimal("500.00"),
            cited_clauses=("GP-3.3",),
        )
    )

    assert decision.requires_human
    rule_ids = {ruling.rule_id for ruling in decision.decisive}
    assert "R-DISCRETION-BOUND" in rule_ids


def test_platinum_status_does_not_raise_the_ceiling(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(
            resolution=Resolution.STORE_CREDIT,
            intent=Intent.LATE_DELIVERY,
            amount=Decimal("400.00"),
            order_total=Decimal("500.00"),
            cited_clauses=("GP-3.3",),
            tier=CustomerTier.PLATINUM,
        )
    ).requires_human


def test_repeated_goodwill_needs_a_reviewer(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(
            resolution=Resolution.STORE_CREDIT,
            intent=Intent.LATE_DELIVERY,
            amount=Decimal("10.00"),
            cited_clauses=("GP-4.2",),
            prior_goodwill_grants=2,
        )
    ).requires_human


# ---------------------------------------------------------------------------
# Exclusions, and the exception that swallows them
# ---------------------------------------------------------------------------


def test_a_final_sale_item_cannot_be_returned_on_a_change_of_mind(
    engine: PolicyEngine,
) -> None:
    assert engine.evaluate(
        ctx(
            intent=Intent.CHANGED_MIND,
            blocking_conditions=("final_sale_item",),
            cited_clauses=("RP-2.1",),
        )
    ).denied


def test_rp_6_4_lets_a_faulty_final_sale_item_through(engine: PolicyEngine) -> None:
    """An exclusion never defeats a claim for a damaged item."""
    assert engine.evaluate(
        ctx(intent=Intent.DAMAGED_ON_ARRIVAL, blocking_conditions=("final_sale_item",))
    ).permitted


@pytest.mark.parametrize(
    "condition", ["final_sale_item", "hygiene_sensitive_item", "perishable_item"]
)
def test_every_exclusion_yields_to_a_fault_based_claim(
    engine: PolicyEngine, condition: str
) -> None:
    assert engine.evaluate(
        ctx(intent=Intent.WRONG_ITEM, blocking_conditions=(condition,))
    ).permitted


def test_an_opened_hygiene_item_is_refused_on_a_change_of_mind(
    engine: PolicyEngine,
) -> None:
    assert engine.evaluate(
        ctx(
            intent=Intent.CHANGED_MIND,
            blocking_conditions=("hygiene_sensitive_item",),
            cited_clauses=("RP-6.2",),
        )
    ).denied


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def test_a_late_change_of_mind_is_refused(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(intent=Intent.CHANGED_MIND, days_since_delivery=45, cited_clauses=("RP-2.1",))
    ).denied


def test_gold_members_get_sixty_days(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(
            intent=Intent.CHANGED_MIND,
            days_since_delivery=45,
            tier=CustomerTier.GOLD,
            cited_clauses=("RP-2.4",),
        )
    ).permitted


def test_the_window_does_not_bar_a_fault_based_claim(engine: PolicyEngine) -> None:
    """RP-6.4 again: two hundred days late, but the wrong item was sent."""
    decision = engine.evaluate(
        ctx(intent=Intent.WRONG_ITEM, days_since_delivery=200, cited_clauses=("RP-7.1",))
    )
    assert "R-WINDOW" not in {ruling.rule_id for ruling in decision.rulings}


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def test_a_damaged_item_refund_may_not_be_reduced(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(resolution=Resolution.PARTIAL_REFUND, cited_clauses=("RP-3.2",))
    ).denied


def test_amb_01_late_damage_report_goes_to_a_person(engine: PolicyEngine) -> None:
    """RP-4.2 sets a 48-hour deadline and attaches no consequence to missing it.

    Neither reading may be picked automatically, because one of them costs the
    customer an entitlement RP-4.1 grants unconditionally.
    """
    decision = engine.evaluate(ctx(days_since_delivery=12))

    assert decision.requires_human
    assert "R-DAMAGE-LATE-REPORT" in {r.rule_id for r in decision.decisive}
    assert "RP-4.2" in decision.clauses


def test_damage_reported_promptly_is_settled(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx(days_since_delivery=1)).permitted


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def test_amb_02_evidenced_non_receipt_is_referred_not_settled(
    engine: PolicyEngine,
) -> None:
    """RP-5.4 is a direction to a reviewer, not a licence to automate."""
    decision = engine.evaluate(
        ctx(
            intent=Intent.NEVER_ARRIVED,
            evidence_strength=EvidenceStrength.STRONG,
            cited_clauses=("RP-5.4",),
            amount=Decimal("40.00"),
        )
    )

    assert decision.requires_human
    assert "R-EVIDENCED-DELIVERY" in {r.rule_id for r in decision.decisive}


def test_weak_evidence_upholds_the_claim(engine: PolicyEngine) -> None:
    assert engine.evaluate(
        ctx(
            intent=Intent.NEVER_ARRIVED,
            evidence_strength=EvidenceStrength.WEAK,
            cited_clauses=("DP-5.3",),
        )
    ).permitted


# ---------------------------------------------------------------------------
# Abuse
# ---------------------------------------------------------------------------


def test_rp_11_4_forbids_an_automated_decline(engine: PolicyEngine) -> None:
    """The rule that stops the fraud story becoming the failure story."""
    decision = engine.evaluate(
        ctx(
            resolution=Resolution.REJECTED,
            intent=Intent.NEVER_ARRIVED,
            amount=None,
            cited_clauses=("RP-11.2",),
            return_rate=0.9,
            delivered_orders=10,
            accounts_at_address=3,
            never_arrived_claims=5,
            evidence_strength=EvidenceStrength.STRONG,
        )
    )

    assert decision.requires_human
    assert "R-ABUSE-NO-AUTO-DECLINE" in {r.rule_id for r in decision.decisive}


def test_two_indicators_send_a_favourable_decision_to_a_person(
    engine: PolicyEngine,
) -> None:
    decision = engine.evaluate(
        ctx(
            intent=Intent.NEVER_ARRIVED,
            evidence_strength=EvidenceStrength.STRONG,
            return_rate=0.9,
            delivered_orders=10,
            never_arrived_claims=5,
            cited_clauses=("DP-5.3",),
        )
    )
    assert decision.requires_human


def test_one_indicator_alone_does_not_trip_rp_11_3(engine: PolicyEngine) -> None:
    """RP-11.3 requires more than one indicator, and means it."""
    context = ctx(
        intent=Intent.CHANGED_MIND,
        return_rate=0.9,
        delivered_orders=10,
        cited_clauses=("RP-2.1",),
    )
    assert len(context.abuse_indicators()) == 1

    decision = engine.evaluate(context)
    assert "R-ABUSE-INDICATORS" not in {r.rule_id for r in decision.rulings}


def test_a_short_history_is_not_a_pattern(engine: PolicyEngine) -> None:
    """Two orders and one return is not a return rate worth acting on."""
    context = ctx(return_rate=0.5, delivered_orders=2)
    assert context.abuse_indicators() == ()


def test_tier_never_overrides_the_abuse_rules(engine: PolicyEngine) -> None:
    """RP-12.3, stated because waving a Platinum member through is the shortcut."""
    assert engine.evaluate(
        ctx(
            intent=Intent.NEVER_ARRIVED,
            tier=CustomerTier.PLATINUM,
            evidence_strength=EvidenceStrength.STRONG,
            return_rate=0.9,
            delivered_orders=10,
            never_arrived_claims=5,
            cited_clauses=("DP-5.3",),
        )
    ).requires_human


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------


def test_a_request_for_human_review_is_always_honoured(engine: PolicyEngine) -> None:
    assert engine.evaluate(ctx(customer_requested_human=True)).requires_human


def test_amb_05_a_platinum_rejection_cannot_be_automated(engine: PolicyEngine) -> None:
    """ "Extended consideration" is never defined, so it cannot be denied by code."""
    decision = engine.evaluate(
        ctx(
            resolution=Resolution.REJECTED,
            intent=Intent.CHANGED_MIND,
            amount=None,
            tier=CustomerTier.PLATINUM,
            cited_clauses=("RP-2.1",),
        )
    )

    assert decision.requires_human
    assert "R-PLATINUM-CONSIDERATION" in {r.rule_id for r in decision.decisive}


# ---------------------------------------------------------------------------
# The guardrail adapter
# ---------------------------------------------------------------------------


def test_the_guardrail_adapter_rejects_an_unknown_resolution(engine: PolicyEngine) -> None:
    permitted, reason = engine.permits(
        decision="give_them_whatever_they_want", amount=None, cited_clauses=("RP-4.1",)
    )
    assert not permitted
    assert "not a resolution" in reason


def test_the_guardrail_adapter_catches_an_uncited_decision(engine: PolicyEngine) -> None:
    permitted, reason = engine.permits(
        decision="full_refund", amount=Decimal("10.00"), cited_clauses=()
    )
    assert not permitted
    assert "no policy clause" in reason


def test_the_guardrail_adapter_passes_a_sound_decision(engine: PolicyEngine) -> None:
    permitted, _ = engine.permits(
        decision="full_refund", amount=Decimal("10.00"), cited_clauses=("RP-4.1",)
    )
    assert permitted


# ---------------------------------------------------------------------------
# Human approval
# ---------------------------------------------------------------------------


def test_approval_satisfies_a_requirement_for_review(engine: PolicyEngine) -> None:
    """A person looked at it. "A person must look at this" is now satisfied.

    Without this the engine keeps reporting REQUIRE_HUMAN after the human said
    yes, and the output guardrail blocks the very reply the approval authorised.
    """
    over_ceiling = ctx(amount=Decimal("500.00"), order_total=Decimal("600.00"))

    assert engine.evaluate(over_ceiling).requires_human

    from dataclasses import replace

    assert engine.evaluate(replace(over_ceiling, human_approved=True)).permitted


def test_the_ceiling_ruling_stays_on_the_record_after_approval(
    engine: PolicyEngine,
) -> None:
    """The dossier should still show that the ceiling was reached."""
    from dataclasses import replace

    decision = engine.evaluate(
        replace(
            ctx(amount=Decimal("500.00"), order_total=Decimal("600.00")),
            human_approved=True,
        )
    )

    assert decision.permitted
    assert "R-CEILING" in {ruling.rule_id for ruling in decision.rulings}


def test_approval_does_not_overturn_a_denial(engine: PolicyEngine) -> None:
    """Approval answers a requirement for review. It is not a licence."""
    from dataclasses import replace

    over_refund = ctx(amount=Decimal("100.00"), order_total=Decimal("60.00"))

    assert engine.evaluate(replace(over_refund, human_approved=True)).denied
