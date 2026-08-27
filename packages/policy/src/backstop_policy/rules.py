"""The rules.

Each rule is a small pure function with the clauses it implements attached to it.
That attachment is the whole design: a ruling can name the clause it came from, so
a decision dossier reads "declined under RP-6.1" rather than "the system said no",
and a change to a clause has an obvious place to land.

Rules never mutate anything and never see a model. They take facts and return a
:class:`Ruling` or ``None`` for "this rule has nothing to say here".

The ordering of effects, strongest first, is ``DENY`` > ``REQUIRE_HUMAN`` >
``PERMIT``. A single deny is decisive. That asymmetry is deliberate: it is much
worse to pay out on a claim policy forbids than to send a legitimate one to a
person.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from backstop_policy.context import (
    CustomerTier,
    EvidenceStrength,
    Intent,
    PolicyContext,
    Resolution,
)


class Effect(IntEnum):
    """Ordered so the strongest ruling in a set is ``max(effects)``."""

    PERMIT = 10
    REQUIRE_HUMAN = 20
    DENY = 30


@dataclass(frozen=True, slots=True)
class Ruling:
    rule_id: str
    effect: Effect
    reason: str
    clauses: tuple[str, ...]

    #: Whether this ruling exists because the policy contradicts itself, as
    #: opposed to because a clear rule applies.
    #:
    #: The distinction decides what happens next. A clear rule that needs a human
    #: - an amount over the ceiling - goes straight to the approval queue: there is
    #: nothing to argue about, someone just has to decide. A ruling flagged here
    #: means the clauses genuinely pull in two directions, and *that* is worth
    #: convening the deliberation room for, so the person who decides sees both
    #: cases argued rather than having to construct them.
    ambiguous: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "effect": self.effect.name.lower(),
            "reason": self.reason,
            "clauses": list(self.clauses),
            "ambiguous": self.ambiguous,
        }


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    clauses: tuple[str, ...]
    description: str
    evaluate: Callable[[PolicyContext], Ruling | None]


def _rule(
    rule_id: str, clauses: tuple[str, ...], description: str
) -> Callable[[Callable[[PolicyContext], Ruling | None]], Rule]:
    def decorate(function: Callable[[PolicyContext], Ruling | None]) -> Rule:
        return Rule(id=rule_id, clauses=clauses, description=description, evaluate=function)

    return decorate


def _ruling(
    rule: str,
    effect: Effect,
    reason: str,
    clauses: tuple[str, ...],
    *,
    ambiguous: bool = False,
) -> Ruling:
    return Ruling(rule_id=rule, effect=effect, reason=reason, clauses=clauses, ambiguous=ambiguous)


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


@_rule("R-OVER-REFUND", ("RP-8.1",), "A refund may not exceed what was paid.")
def over_refund(context: PolicyContext) -> Ruling | None:
    if context.amount is None or not context.resolution.moves_money:
        return None

    if context.already_refunded + context.amount > context.order_total:
        return _ruling(
            "R-OVER-REFUND",
            Effect.DENY,
            f"refunding {context.amount} would take the total past the order value "
            f"of {context.order_total} ({context.already_refunded} already refunded)",
            ("RP-8.1",),
        )
    return None


@_rule("R-CITATION", ("RP-11.3",), "A resolution must rest on a stated clause.")
def citation_required(context: PolicyContext) -> Ruling | None:
    if context.resolution is Resolution.ESCALATE:
        return None
    if context.cited_clauses:
        return None

    return _ruling(
        "R-CITATION",
        Effect.REQUIRE_HUMAN,
        "no policy clause was cited in support of this resolution",
        ("RP-11.3",),
    )


# ---------------------------------------------------------------------------
# Ceilings - the AMB-04 case
# ---------------------------------------------------------------------------


@_rule(
    "R-CEILING",
    ("GP-3.1", "GP-3.2", "RP-13.1"),
    "Money above the automatic ceiling needs a person.",
)
def approval_ceiling(context: PolicyContext) -> Ruling | None:
    if context.amount is None or not context.resolution.moves_money:
        return None

    if context.amount > context.auto_approve_ceiling:
        return _ruling(
            "R-CEILING",
            Effect.REQUIRE_HUMAN,
            f"{context.amount} exceeds the automatic approval ceiling of "
            f"{context.auto_approve_ceiling}",
            ("GP-3.2", "RP-13.1"),
        )
    return None


@_rule(
    "R-DISCRETION-BOUND",
    ("GP-3.1", "GP-3.3", "GP-6.2"),
    "Agent discretion does not create authority above the ceiling.",
)
def discretion_is_bound(context: PolicyContext) -> Ruling | None:
    """The planted ambiguity AMB-04, settled in code.

    GP-3.3 permits goodwill "at the agent's discretion" and states no limit, which
    reads as an independent grant of authority. GP-3.1 caps goodwill at the
    automatic ceiling. The prose does not resolve which governs.

    This rule resolves it: the ceiling binds, whatever GP-3.3 appears to permit.
    An agent that talks itself into GP-3.3 authority is exactly the failure the
    guardrail plane exists to prevent, and a debate between agents is the wrong
    instrument - the answer should not depend on who argued better.
    """
    if context.resolution is not Resolution.STORE_CREDIT or context.amount is None:
        return None

    if "GP-3.3" in context.cited_clauses and context.amount > context.auto_approve_ceiling:
        return _ruling(
            "R-DISCRETION-BOUND",
            Effect.REQUIRE_HUMAN,
            "GP-3.3 discretion is exercised inside the GP-3.1 ceiling, not above it; "
            "tier status does not raise it either (GP-6.2)",
            ("GP-3.1", "GP-3.3", "GP-6.2"),
        )
    return None


@_rule("R-GOODWILL-REPEAT", ("GP-5.2",), "Repeated goodwill needs a reviewer.")
def repeated_goodwill(context: PolicyContext) -> Ruling | None:
    if context.resolution is not Resolution.STORE_CREDIT:
        return None
    if context.prior_goodwill_grants < 2:
        return None

    return _ruling(
        "R-GOODWILL-REPEAT",
        Effect.REQUIRE_HUMAN,
        f"{context.prior_goodwill_grants} goodwill grants in the preceding period",
        ("GP-5.2",),
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@_rule(
    "R-FINAL-SALE",
    ("RP-6.1", "RP-6.4"),
    "Final-sale items return only when faulty.",
)
def final_sale(context: PolicyContext) -> Ruling | None:
    if not context.is_final_sale or not context.resolution.favours_customer:
        return None

    # RP-6.4: an exclusion never defeats a claim for a faulty, damaged or wrong
    # item. Encoding the exception here rather than in the catalogue tool is the
    # point - the tool reports facts, the rule applies the exception.
    if context.intent.is_fault_based:
        return None

    return _ruling(
        "R-FINAL-SALE",
        Effect.DENY,
        "the item was sold as final sale and the claim is not fault-based",
        ("RP-6.1",),
    )


@_rule("R-HYGIENE", ("RP-6.2", "RP-6.4"), "Opened hygiene items do not return.")
def hygiene(context: PolicyContext) -> Ruling | None:
    if not context.is_hygiene_sensitive or not context.resolution.favours_customer:
        return None
    if context.intent.is_fault_based:
        return None

    return _ruling(
        "R-HYGIENE",
        Effect.DENY,
        "hygiene-sensitive item and the claim is not fault-based",
        ("RP-6.2",),
    )


@_rule("R-PERISHABLE", ("RP-6.3", "RP-6.4"), "Perishables return only if spoiled.")
def perishable(context: PolicyContext) -> Ruling | None:
    if not context.is_perishable or not context.resolution.favours_customer:
        return None
    if context.intent.is_fault_based:
        return None

    return _ruling(
        "R-PERISHABLE",
        Effect.DENY,
        "perishable goods and the claim is not fault-based",
        ("RP-6.3",),
    )


@_rule("R-WINDOW", ("RP-2.1", "RP-2.4", "RP-6.4"), "Returns close after the window.")
def return_window(context: PolicyContext) -> Ruling | None:
    if not context.resolution.favours_customer:
        return None
    if context.effective_within_window:
        return None
    if context.intent.is_fault_based:
        return None

    return _ruling(
        "R-WINDOW",
        Effect.DENY,
        f"{context.days_since_delivery} days since delivery exceeds the "
        f"{context.window_days}-day window for this tier",
        ("RP-2.1", "RP-2.4"),
    )


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


@_rule("R-DAMAGE-NO-DEDUCTION", ("RP-4.4",), "Damaged-on-arrival refunds are not reduced.")
def damage_no_deduction(context: PolicyContext) -> Ruling | None:
    if context.intent is not Intent.DAMAGED_ON_ARRIVAL:
        return None
    if context.resolution is not Resolution.PARTIAL_REFUND:
        return None

    return _ruling(
        "R-DAMAGE-NO-DEDUCTION",
        Effect.DENY,
        "no deduction may be applied to a damaged-on-arrival refund",
        ("RP-4.4",),
    )


@_rule(
    "R-DAMAGE-LATE-REPORT",
    ("RP-4.1", "RP-4.2"),
    "Damage reported after 48 hours: the planted conflict AMB-01.",
)
def damage_reported_late(context: PolicyContext) -> Ruling | None:
    """AMB-01, routed to a human rather than resolved.

    RP-4.2 requires damage to be reported within 48 hours but attaches no
    consequence to missing it. RP-4.1 grants an unconditional entitlement with no
    time limit of its own. Read one way RP-4.2 is a condition of the remedy; read
    another it is our own deadline for recovering from the carrier.

    The text does not say, so this rule does not decide. It refuses to let an
    automated system pick a reading that costs a customer their entitlement, and
    hands it to a person with the conflict named.
    """
    if context.intent is not Intent.DAMAGED_ON_ARRIVAL:
        return None
    if context.days_since_delivery is None or context.days_since_delivery <= 2:
        return None

    return _ruling(
        "R-DAMAGE-LATE-REPORT",
        Effect.REQUIRE_HUMAN,
        f"damage reported {context.days_since_delivery} days after delivery; "
        f"RP-4.2 sets a 48-hour reporting deadline but RP-4.1 grants the remedy "
        f"unconditionally, and the policy does not say which governs",
        ("RP-4.1", "RP-4.2"),
        ambiguous=True,
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


@_rule(
    "R-EVIDENCED-DELIVERY",
    ("RP-5.3", "RP-5.4", "DP-5.2"),
    "Non-receipt against strong evidence is referred, never auto-settled.",
)
def evidenced_delivery(context: PolicyContext) -> Ruling | None:
    """AMB-02.

    RP-5.3 refers the claim for review. RP-5.4 says a first-time claim from an
    account in good standing should be resolved in the customer's favour - but
    never says who may apply it, and "absent other concerns" is undefined.

    An automated system applying RP-5.4 to itself would be reading a clause about
    reviewer judgement as a grant of automation. It refers instead.
    """
    if context.intent is not Intent.NEVER_ARRIVED:
        return None
    if context.evidence_strength is not EvidenceStrength.STRONG:
        return None

    return _ruling(
        "R-EVIDENCED-DELIVERY",
        Effect.REQUIRE_HUMAN,
        "the carrier holds a signature or photograph, so RP-5.3 refers this for "
        "review; RP-5.4 is a direction to the reviewer, not a licence to automate",
        ("RP-5.3", "RP-5.4"),
    )


@_rule("R-WEAK-EVIDENCE", ("DP-3.2", "DP-5.3", "RP-5.2"), "Weak evidence upholds the claim.")
def weak_evidence(context: PolicyContext) -> Ruling | None:
    if context.intent is not Intent.NEVER_ARRIVED:
        return None
    if context.evidence_strength is EvidenceStrength.STRONG:
        return None
    if not context.resolution.favours_customer:
        return None

    return _ruling(
        "R-WEAK-EVIDENCE",
        Effect.PERMIT,
        "a scan without a signature or photograph is weak evidence under DP-3.2, "
        "so DP-5.3 upholds the claim",
        ("DP-3.2", "DP-5.3"),
    )


# ---------------------------------------------------------------------------
# Abuse
# ---------------------------------------------------------------------------


@_rule(
    "R-ABUSE-NO-AUTO-DECLINE",
    ("RP-11.4",),
    "An automated system may refer under RP-11, never refuse.",
)
def abuse_never_auto_declines(context: PolicyContext) -> Ruling | None:
    """RP-11.4, stated plainly and enforced plainly.

    This is the rule that stops the fraud story becoming the failure story. The
    system can gather evidence and recommend; a person declines.
    """
    if context.resolution is not Resolution.REJECTED:
        return None
    if not context.abuse_indicators():
        return None

    return _ruling(
        "R-ABUSE-NO-AUTO-DECLINE",
        Effect.REQUIRE_HUMAN,
        "RP-11.4 forbids an automated decline on abuse grounds; "
        f"indicators present: {'; '.join(context.abuse_indicators())}",
        ("RP-11.4",),
    )


@_rule(
    "R-ABUSE-INDICATORS",
    ("RP-11.2", "RP-11.3", "RP-12.3"),
    "Two or more abuse indicators require a person.",
)
def abuse_indicators(context: PolicyContext) -> Ruling | None:
    indicators = context.abuse_indicators()
    if len(indicators) < 2:
        return None
    if not context.resolution.favours_customer:
        return None

    # RP-12.3: tier status never overrides RP-11. Stated explicitly because the
    # tempting shortcut is to wave a Platinum member through.
    return _ruling(
        "R-ABUSE-INDICATORS",
        Effect.REQUIRE_HUMAN,
        f"{len(indicators)} abuse indicators present ({'; '.join(indicators)}); "
        f"RP-11.3 requires more than one and this reaches that threshold",
        ("RP-11.2", "RP-11.3", "RP-12.3"),
    )


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------


@_rule(
    "R-REPEATED-SINGLE-INDICATOR",
    ("RP-11.2", "RP-11.3"),
    "One indicator, many times over: the planted conflict AMB-03.",
)
def repeated_single_indicator(context: PolicyContext) -> Ruling | None:
    """AMB-03.

    RP-11.3 requires more than one indicator. RP-11.2 lists "repeated non-receipt
    claims against deliveries the carrier can evidence" as a *single* indicator.

    A customer with six such claims and nothing else has triggered one indicator
    six times. Whether that satisfies a rule asking for two is not something the
    text answers, and it is a question with a real argument on each side - which
    makes it worth putting to the room rather than settling by fiat.
    """
    indicators = context.abuse_indicators()
    if len(indicators) != 1:
        return None
    if context.never_arrived_claims < 4:
        return None
    if context.evidence_strength is not EvidenceStrength.STRONG:
        return None

    return _ruling(
        "R-REPEATED-SINGLE-INDICATOR",
        Effect.REQUIRE_HUMAN,
        f"one abuse indicator ({indicators[0]}) has recurred "
        f"{context.never_arrived_claims} times; RP-11.3 asks for more than one "
        f"indicator and does not say whether repetition of one counts",
        ("RP-11.2", "RP-11.3"),
        ambiguous=True,
    )


@_rule("R-CUSTOMER-REQUEST", ("RP-13.2",), "A request for human review is honoured.")
def customer_requested_human(context: PolicyContext) -> Ruling | None:
    if not context.customer_requested_human:
        return None

    return _ruling(
        "R-CUSTOMER-REQUEST",
        Effect.REQUIRE_HUMAN,
        "the customer asked for human review, which RP-13.2 requires be honoured",
        ("RP-13.2",),
    )


@_rule(
    "R-PLATINUM-CONSIDERATION",
    ("RP-12.2", "GP-6.1", "RP-12.3"),
    "Extended consideration is undefined: AMB-05.",
)
def platinum_consideration(context: PolicyContext) -> Ruling | None:
    """AMB-05.

    RP-12.2 entitles Platinum members to "extended consideration" and never
    defines it. GP-6.1 defines it for goodwill only. Whether that reaches other
    discretionary decisions is unstated.

    Only engages on a decision *against* a Platinum member, because that is the
    only direction in which the undefined entitlement could have been denied them.
    """
    if context.tier is not CustomerTier.PLATINUM:
        return None
    if context.resolution is not Resolution.REJECTED:
        return None

    return _ruling(
        "R-PLATINUM-CONSIDERATION",
        Effect.REQUIRE_HUMAN,
        "RP-12.2 entitles this member to extended consideration on a discretionary "
        "decision and does not define what that means; a rejection cannot be "
        "automated against an undefined entitlement",
        ("RP-12.2", "GP-6.1"),
        ambiguous=True,
    )


#: Evaluated in this order. Order does not change the outcome - the strongest
#: effect wins regardless - but it decides the order rulings are recorded in,
#: which is the order a person reads them.
ALL_RULES: tuple[Rule, ...] = (
    over_refund,
    citation_required,
    approval_ceiling,
    discretion_is_bound,
    repeated_goodwill,
    final_sale,
    hygiene,
    perishable,
    return_window,
    damage_no_deduction,
    damage_reported_late,
    evidenced_delivery,
    weak_evidence,
    abuse_never_auto_declines,
    abuse_indicators,
    repeated_single_indicator,
    customer_requested_human,
    platinum_consideration,
)


__all__ = ["ALL_RULES", "Effect", "Rule", "Ruling"]
