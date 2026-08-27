"""The policy engine.

Runs every rule, keeps every ruling, and returns the strongest effect. Nothing is
short-circuited: a rule that would have denied is recorded even when another rule
already denied, because a decision dossier should show every reason, not the first
one found.

This class is what the output guardrail calls to re-check a model's decision, and
what the graph calls to decide whether a resolution can be executed at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backstop_policy.context import Intent, PolicyContext, Resolution
from backstop_policy.rules import ALL_RULES, Effect, Rule, Ruling


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """What the rules concluded, and why."""

    effect: Effect
    rulings: tuple[Ruling, ...]

    @property
    def permitted(self) -> bool:
        return self.effect is Effect.PERMIT

    @property
    def requires_human(self) -> bool:
        return self.effect is Effect.REQUIRE_HUMAN

    @property
    def denied(self) -> bool:
        return self.effect is Effect.DENY

    @property
    def decisive(self) -> tuple[Ruling, ...]:
        """The rulings that produced the outcome."""
        return tuple(ruling for ruling in self.rulings if ruling.effect is self.effect)

    @property
    def needs_deliberation(self) -> bool:
        """Whether a decisive ruling rests on a contradiction in the policy.

        A clear rule requiring a human goes to the approval queue. A contradiction
        goes to the room first, so the person deciding sees both cases argued.
        """
        return any(ruling.ambiguous for ruling in self.decisive)

    @property
    def ambiguous_rules(self) -> tuple[str, ...]:
        return tuple(ruling.rule_id for ruling in self.decisive if ruling.ambiguous)

    @property
    def clauses(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ruling in self.decisive:
            for clause in ruling.clauses:
                if clause not in seen:
                    seen.append(clause)
        return tuple(seen)

    def explain(self) -> str:
        if not self.decisive:
            return "no rule had anything to say"
        return "; ".join(ruling.reason for ruling in self.decisive)

    def as_dict(self) -> dict[str, object]:
        return {
            "effect": self.effect.name.lower(),
            "clauses": list(self.clauses),
            "explanation": self.explain(),
            "needs_deliberation": self.needs_deliberation,
            "ambiguous_rules": list(self.ambiguous_rules),
            "rulings": [ruling.as_dict() for ruling in self.rulings],
        }


class PolicyEngine:
    """Deterministic evaluation of a proposed resolution."""

    def __init__(self, rules: tuple[Rule, ...] = ALL_RULES) -> None:
        duplicates = {rule.id for rule in rules if sum(r.id == rule.id for r in rules) > 1}
        if duplicates:
            raise ValueError(f"duplicate rule ids: {', '.join(sorted(duplicates))}")
        self._rules = rules

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self._rules

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        rulings = tuple(
            ruling for rule in self._rules if (ruling := rule.evaluate(context)) is not None
        )

        # No rule objecting is a permit. That is safe only because the money-moving
        # path is *also* gated by the tool gateway's scopes and approval ceiling -
        # this engine is one of two independent checks, not the only one.
        effect = max((ruling.effect for ruling in rulings), default=Effect.PERMIT)

        # A human has reviewed, so every "a person must decide this" is satisfied.
        # The rulings stay on record - the dossier should still show that the
        # ceiling was reached and who cleared it - but they no longer hold the
        # decision open. A DENY is untouched: approval answers a requirement for
        # review, it does not overturn a prohibition.
        if context.human_approved and effect is Effect.REQUIRE_HUMAN:
            effect = Effect.PERMIT

        return PolicyDecision(effect=effect, rulings=rulings)

    # -- the guardrail PolicyCheck protocol --------------------------------

    def permits(
        self,
        *,
        decision: str,
        amount: Decimal | None,
        cited_clauses: tuple[str, ...],
        human_approved: bool = False,
    ) -> tuple[bool, str]:
        """Adapter for the output guardrail.

        Deliberately narrow: the guardrail passes only what a model produced, so
        this can only catch decisions that are wrong *on their face*. The full
        check runs in the graph, where the facts are in hand.
        """
        try:
            resolution = Resolution(decision)
        except ValueError:
            return False, f"{decision!r} is not a resolution this system recognises"

        context = PolicyContext(
            intent=Intent.OTHER,
            resolution=resolution,
            amount=amount,
            cited_clauses=cited_clauses,
            order_total=amount or Decimal("0"),
            human_approved=human_approved,
        )
        outcome = self.evaluate(context)

        if outcome.permitted:
            return True, ""
        return False, outcome.explain()


__all__ = ["PolicyDecision", "PolicyEngine"]
