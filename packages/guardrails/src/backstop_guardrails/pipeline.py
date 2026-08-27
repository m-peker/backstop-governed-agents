"""The two guardrail passes.

:class:`InputGuardrail` runs before anything reaches a model. :class:`OutputGuardrail`
runs before anything reaches a customer.

The output pass is the one that carries the weight, and its most important check is
the least clever: after the model has produced a decision, the deterministic policy
engine re-derives whether that decision was permissible, and disagreement is
decisive. The model proposes; code disposes. Every other output check - groundedness,
leak scanning, tone - sits on top of that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backstop_guardrails.events import (
    Action,
    Detector,
    GuardrailEvent,
    GuardrailVerdict,
    Severity,
)
from backstop_guardrails.injection import canary_leaked, new_canary, scan
from backstop_guardrails.normalise import normalise
from backstop_guardrails.pii import Vault, tokenise
from backstop_guardrails.spotlight import Provenance, Spotlight


@dataclass(frozen=True, slots=True)
class SanitisedInput:
    """What the graph receives instead of raw customer text."""

    text: str
    """Normalised and tokenised. Safe to place inside a spotlight block."""

    original: str
    """Exactly what arrived. Kept for the audit record, never sent to a model."""

    vault: Vault
    spotlight: Spotlight
    canary: str
    verdict: GuardrailVerdict

    def prompt_block(self, *, source: Provenance = Provenance.CUSTOMER, label: str = "") -> str:
        """The text, wrapped and framed, ready to drop into a user message."""
        return self.spotlight.wrap(self.text, source=source, label=label)


class InputGuardrail:
    """Normalise, tokenise, scan. In that order, for a reason.

    Normalisation first, because every later detector matches patterns and an
    attacker who can change the bytes defeats all of them at once.

    Tokenisation before injection scanning, because the scan should run over the
    text a model will actually see - and because a name that happens to contain a
    trigger word should not fire the scanner.
    """

    def __init__(self, *, known_names: frozenset[str] | None = None) -> None:
        self._known_names = known_names

    def run(self, raw: str, *, ticket_id: str) -> SanitisedInput:
        cleaned = normalise(raw)
        tokenised = tokenise(cleaned.text, ticket_id=ticket_id, known_names=self._known_names)
        injection = scan(tokenised.text)

        events = [*cleaned.events, *tokenised.events, *injection.events]
        events.extend(self._evasion(cleaned, injection))

        return SanitisedInput(
            text=tokenised.text,
            original=raw,
            vault=tokenised.vault,
            spotlight=Spotlight.new(),
            canary=new_canary(),
            verdict=GuardrailVerdict(events=tuple(events)),
        )

    @staticmethod
    def _evasion(cleaned: object, injection: object) -> list[GuardrailEvent]:
        """Obfuscation plus an override phrase is not two coincidences.

        Either finding alone is survivable. A customer can quote an instruction
        they were sent, and a stray zero-width character can arrive from a copy
        and paste. Trigger words with invisible characters *inside them* is a
        deliberate attempt to get past a pattern match, and the combination is
        what makes it conclusive.
        """
        obfuscated = any(
            event.detector is Detector.ENCODING and event.severity >= Severity.HIGH
            for event in getattr(cleaned, "events", ())
        )
        if not obfuscated or not getattr(injection, "suspicious", False):
            return []

        return [
            GuardrailEvent(
                detector=Detector.INJECTION_STRUCTURE,
                severity=Severity.CRITICAL,
                action=Action.BLOCK,
                summary=(
                    "instruction-override language was hidden behind character "
                    "obfuscation; the combination is deliberate evasion"
                ),
            )
        ]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class PolicyCheck(Protocol):
    """The deterministic re-check of a model's decision.

    Implemented by the policy engine. Declared as a Protocol here so the guardrail
    package does not depend on it - the dependency runs the other way.
    """

    def permits(
        self,
        *,
        decision: str,
        amount: Decimal | None,
        cited_clauses: tuple[str, ...],
        human_approved: bool = False,
    ) -> tuple[bool, str]: ...


@dataclass(frozen=True, slots=True)
class OutputCandidate:
    """What the model produced, before it is allowed out."""

    reply: str
    decision: str
    amount: Decimal | None
    cited_clauses: tuple[str, ...]

    #: Whether a person reviewed and approved this outcome. The policy re-check
    #: needs it: without it the ceiling rule fires again and blocks the reply the
    #: approval authorised.
    human_approved: bool = False


class OutputGuardrail:
    """Everything that must hold before a reply reaches a customer."""

    def __init__(
        self,
        *,
        retrieved_clause_ids: frozenset[str],
        policy_check: PolicyCheck | None = None,
        authorised_channels: frozenset[str] = frozenset({"email", "console"}),
    ) -> None:
        self._retrieved = retrieved_clause_ids
        self._policy_check = policy_check
        self._authorised = authorised_channels

    def run(
        self,
        candidate: OutputCandidate,
        *,
        sanitised: SanitisedInput,
        channel: str,
    ) -> GuardrailVerdict:
        events: list[GuardrailEvent] = []

        events.extend(self._check_canary(candidate, sanitised))
        events.extend(self._check_groundedness(candidate))
        events.extend(self._check_policy(candidate))
        events.extend(self._check_pii(candidate, sanitised, channel))

        return GuardrailVerdict(events=tuple(events))

    def release(
        self, candidate: OutputCandidate, *, sanitised: SanitisedInput, channel: str
    ) -> str:
        """Resolve placeholders for an authorised channel.

        Call only after :meth:`run` returned a verdict that is not blocked.
        """
        if channel not in self._authorised:
            raise PermissionError(f"channel {channel!r} is not authorised to receive personal data")
        return sanitised.vault.resolve(candidate.reply)

    # -- checks -----------------------------------------------------------

    def _check_canary(
        self, candidate: OutputCandidate, sanitised: SanitisedInput
    ) -> list[GuardrailEvent]:
        events: list[GuardrailEvent] = []

        leak = canary_leaked(candidate.reply, sanitised.canary)
        if leak:
            events.append(leak)

        if sanitised.spotlight.contains_marker(candidate.reply):
            events.append(
                GuardrailEvent(
                    detector=Detector.CANARY_LEAK,
                    severity=Severity.HIGH,
                    action=Action.BLOCK,
                    summary="the reply reproduced the spotlight delimiter",
                )
            )

        return events

    def _check_groundedness(self, candidate: OutputCandidate) -> list[GuardrailEvent]:
        """Every cited clause must be one that was actually retrieved.

        Catches the failure mode where a model cites a plausible clause number it
        invented. Without this, "as set out in RP-9.7" reads as authoritative and
        RP-9.7 does not exist.
        """
        invented = tuple(
            clause for clause in candidate.cited_clauses if clause not in self._retrieved
        )
        if invented:
            return [
                GuardrailEvent(
                    detector=Detector.GROUNDEDNESS,
                    severity=Severity.CRITICAL,
                    action=Action.BLOCK,
                    summary=f"cited clause(s) never retrieved: {', '.join(invented)}",
                    detail={"invented": list(invented), "retrieved": sorted(self._retrieved)},
                )
            ]

        if not candidate.cited_clauses and candidate.decision != "escalate":
            return [
                GuardrailEvent(
                    detector=Detector.GROUNDEDNESS,
                    severity=Severity.HIGH,
                    action=Action.ESCALATE,
                    summary="a resolution was reached without citing any policy clause",
                )
            ]

        return []

    def _check_policy(self, candidate: OutputCandidate) -> list[GuardrailEvent]:
        if self._policy_check is None:
            return []

        permitted, reason = self._policy_check.permits(
            decision=candidate.decision,
            amount=candidate.amount,
            cited_clauses=candidate.cited_clauses,
            human_approved=candidate.human_approved,
        )
        if permitted:
            return []

        return [
            GuardrailEvent(
                detector=Detector.POLICY_CONFORMANCE,
                severity=Severity.CRITICAL,
                action=Action.BLOCK,
                summary=f"policy engine rejects the proposed decision: {reason}",
                detail={"decision": candidate.decision, "reason": reason},
            )
        ]

    def _check_pii(
        self, candidate: OutputCandidate, sanitised: SanitisedInput, channel: str
    ) -> list[GuardrailEvent]:
        if channel in self._authorised:
            return []

        present = sanitised.vault.unresolved_tokens(candidate.reply)
        if not present:
            return []

        return [
            GuardrailEvent(
                detector=Detector.PII_LEAK,
                severity=Severity.HIGH,
                action=Action.BLOCK,
                summary=(
                    f"reply carries {len(present)} personal-data placeholder(s) but "
                    f"channel {channel!r} is not authorised to resolve them"
                ),
                detail={"placeholder_count": len(present), "channel": channel},
            )
        ]


__all__ = [
    "InputGuardrail",
    "OutputCandidate",
    "OutputGuardrail",
    "PolicyCheck",
    "SanitisedInput",
]
