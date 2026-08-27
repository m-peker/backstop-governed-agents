"""The facts a policy decision is made from.

Everything the rules need, in one immutable object, assembled from tool output
before any rule runs. Nothing in this package reads a database, calls a tool or
talks to a model - which is what makes a ruling reproducible from the audit trail
years later, and what makes the rules unit-testable without any of that machinery.

The context deliberately holds *facts*, never conclusions. ``return_rate`` is here;
``is_abusive`` is not. Turning facts into a conclusion is what the rules do, and
recording which rule did it is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class Resolution(StrEnum):
    """What is being proposed. Mirrors the domain enum plus an escalation route."""

    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    REPLACEMENT = "replacement"
    STORE_CREDIT = "store_credit"
    REJECTED = "rejected"
    ESCALATE = "escalate"

    @property
    def moves_money(self) -> bool:
        return self in (
            Resolution.FULL_REFUND,
            Resolution.PARTIAL_REFUND,
            Resolution.STORE_CREDIT,
        )

    @property
    def favours_customer(self) -> bool:
        return self in (
            Resolution.FULL_REFUND,
            Resolution.PARTIAL_REFUND,
            Resolution.REPLACEMENT,
            Resolution.STORE_CREDIT,
        )


class Intent(StrEnum):
    """Why the customer wrote in."""

    DAMAGED_ON_ARRIVAL = "damaged_on_arrival"
    NEVER_ARRIVED = "never_arrived"
    WRONG_ITEM = "wrong_item"
    LATE_DELIVERY = "late_delivery"
    CHANGED_MIND = "changed_mind"
    SIZE_ISSUE = "size_issue"
    NOT_AS_DESCRIBED = "not_as_described"
    OTHER = "other"

    @property
    def is_fault_based(self) -> bool:
        """Whether the trader is at fault.

        Matters because RP-6.4 says a product exclusion never defeats a claim for
        a faulty, damaged or wrong item - so this property decides whether the
        exclusion rules apply at all.
        """
        return self in (
            Intent.DAMAGED_ON_ARRIVAL,
            Intent.WRONG_ITEM,
            Intent.NOT_AS_DESCRIBED,
            Intent.NEVER_ARRIVED,
        )


class EvidenceStrength(StrEnum):
    """Delivery evidence, per DP-3."""

    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"


class CustomerTier(StrEnum):
    STANDARD = "standard"
    GOLD = "gold"
    PLATINUM = "platinum"


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Facts. Assembled once, then read by every rule."""

    # -- what is proposed -------------------------------------------------
    intent: Intent
    resolution: Resolution
    amount: Decimal | None
    cited_clauses: tuple[str, ...] = ()

    # -- the order --------------------------------------------------------
    order_total: Decimal = Decimal("0")
    already_refunded: Decimal = Decimal("0")

    # -- eligibility ------------------------------------------------------
    within_window: bool = True
    days_since_delivery: int | None = None
    blocking_conditions: tuple[str, ...] = ()

    # -- delivery ---------------------------------------------------------
    evidence_strength: EvidenceStrength = EvidenceStrength.NONE

    # -- the customer -----------------------------------------------------
    tier: CustomerTier = CustomerTier.STANDARD
    tenure_days: int = 365
    return_rate: float = 0.0
    delivered_orders: int = 0
    never_arrived_claims: int = 0
    accounts_at_address: int = 1
    prior_goodwill_grants: int = 0

    # -- process ----------------------------------------------------------
    customer_requested_human: bool = False
    auto_approve_ceiling: Decimal = Decimal("75.00")

    #: Whether a person has already reviewed and approved this exact decision.
    #:
    #: Every REQUIRE_HUMAN ruling is a statement that a person must look at the
    #: case. Once one has, that requirement is met. Without this the engine keeps
    #: reporting "needs a human" after a human said yes, and the output guardrail
    #: - which re-checks the decision before the reply goes out - blocks the very
    #: message the approval authorised.
    #:
    #: A DENY is not affected. Approval satisfies a requirement for review; it
    #: does not overturn a rule that forbids the action outright.
    human_approved: bool = False

    #: Abuse indicators the rules computed, cached so RP-11.3 can count them
    #: without each rule recomputing.
    _indicators: tuple[str, ...] = field(default=(), repr=False)

    @property
    def is_final_sale(self) -> bool:
        return "final_sale_item" in self.blocking_conditions

    @property
    def is_hygiene_sensitive(self) -> bool:
        return "hygiene_sensitive_item" in self.blocking_conditions

    @property
    def is_perishable(self) -> bool:
        return "perishable_item" in self.blocking_conditions

    @property
    def window_days(self) -> int:
        """RP-2.4 gives Gold and Platinum members a longer window."""
        return 60 if self.tier in (CustomerTier.GOLD, CustomerTier.PLATINUM) else 30

    @property
    def effective_within_window(self) -> bool:
        if self.days_since_delivery is None:
            return self.within_window
        return self.days_since_delivery <= self.window_days

    def abuse_indicators(self) -> tuple[str, ...]:
        """RP-11.2 indicators present in these facts.

        Counted rather than judged. RP-11.3 requires more than one, and RP-11.4
        forbids an automated system from declining on them at all - both of which
        are enforced by rules, not here.
        """
        found: list[str] = []

        # A high rate is only meaningful once there is enough history for it to
        # mean anything. Two orders and one return is not a pattern.
        if self.delivered_orders >= 4 and self.return_rate > 0.5:
            found.append("return rate far above the norm")

        if self.accounts_at_address >= 3:
            found.append("several accounts filing claims from one delivery address")

        if self.never_arrived_claims >= 3 and self.evidence_strength is EvidenceStrength.STRONG:
            found.append("repeated non-receipt claims against evidenced deliveries")

        if self.tenure_days < 30 and self.amount is not None and self.amount > Decimal("300"):
            found.append("days-old account making a high-value claim")

        return tuple(found)


__all__ = [
    "CustomerTier",
    "EvidenceStrength",
    "Intent",
    "PolicyContext",
    "Resolution",
]
