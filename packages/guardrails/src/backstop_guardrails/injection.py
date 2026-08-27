"""Prompt injection detection.

Read this first: **detection is not the control.** The controls are the tool
gateway's scopes and the policy engine's re-check of every decision. A jailbroken
model in this system still cannot move money it lacks the scope for. Detection
exists to catch attempts, record them, and route the ticket to a human - not to be
the thing standing between an attacker and a refund.

That distinction is why this module is honest about its own limits and why the
red-team suite reports an attack success rate rather than claiming coverage.

Three layers, deliberately different in kind so that they fail differently:

**Structure.** Untrusted text that tries to close a delimiter, open a new role, or
impersonate a system message. Cheap, precise, near-zero false positives.

**Lexical.** Known instruction-override phrasings, in Turkish and English. Any
single phrase is weak evidence; several together are not.

**Density.** The ratio of imperative, system-directed language to the ordinary
prose of a complaint. A customer describing a broken vase does not write in
instructions. This is the layer that catches phrasings nobody has enumerated.

A fourth mechanism sits alongside them: a canary token placed in the system prompt.
If it ever appears in output, the prompt leaked, and that is a fact rather than a
heuristic.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from backstop_guardrails.events import Action, Detector, GuardrailEvent, Severity

# ---------------------------------------------------------------------------
# Layer 1: structure
# ---------------------------------------------------------------------------

_STRUCTURAL = (
    (re.compile(r"</?(?:system|assistant|user|instructions?|prompt)\s*>", re.I), "role tag"),
    (re.compile(r"^\s*(?:system|assistant)\s*:", re.I | re.M), "role prefix"),
    (re.compile(r"\[/?(?:INST|SYS|系统)\]", re.I), "instruction delimiter"),
    (re.compile(r"<\|[^|>]{1,40}\|>"), "special token"),
    (re.compile(r"-{3,}\s*end of (?:customer|user|untrusted)", re.I), "delimiter escape"),
    (re.compile(r"```\s*(?:system|instructions?)", re.I), "fenced instruction block"),
)

# ---------------------------------------------------------------------------
# Layer 2: lexical
# ---------------------------------------------------------------------------

_OVERRIDE_PHRASES = (
    # English
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions?|prompts?|rules?)",
    r"disregard (?:all |any |the )?(?:previous|prior|above) (?:instructions?|rules?)",
    r"forget (?:everything|all|your) (?:you|instructions?|rules?|training)",
    r"you are (?:now|actually) (?:a|an|in) ",
    r"new (?:instructions?|system prompt|rules?)\s*:",
    r"(?:act|behave|respond) as (?:if|though|a) ",
    r"(?:do not|don'?t) (?:follow|obey|apply) (?:the )?(?:policy|rules?|guidelines?)",
    r"reveal (?:your |the )?(?:system )?(?:prompt|instructions?)",
    r"print (?:your |the )?(?:system )?(?:prompt|instructions?)",
    r"developer mode|jailbreak|DAN mode",
    r"without (?:asking|requiring|needing|the)\s+(?:for\s+)?(?:usual\s+|normal\s+)?"
    r"(?:approval|authoris|authoriz|permission|review|escalation)",
    r"(?:skip|bypass|waive)\s+(?:the\s+)?(?:usual\s+|normal\s+)?"
    r"(?:approval|review|escalation|check)",
    # A claim of internal authority. No override phrasing, no delimiters, no
    # obfuscation - just a plausible assertion about who is speaking. Without
    # this the lexical layer sees nothing at all in the most realistic social
    # attack there is, and the ceiling ends up being the only thing standing.
    r"(?:this is|i am|i'?m)\s+\w+\s+from\s+(?:the\s+)?"
    r"(?:customer operations|customer service|support|the team|management|"
    r"finance|head office|head-office)",
    r"on behalf of\s+(?:the\s+)?(?:customer operations|support|management)\s+team",
    r"approve (?:this|the) (?:refund|request) (?:automatically|immediately|without)",
    r"you (?:must|have to|are required to) (?:issue|approve|refund|grant)",
    # Turkish
    r"(?:önceki|yukarıdaki|tüm) (?:talimatları|kuralları)\s*(?:yok say|unut|görmezden gel)",
    r"talimatları\s*(?:yok say|unut)",
    r"artık (?:bir|sen)\s",
    r"yeni (?:talimat|kural)(?:lar)?\s*:",
    r"(?:onay|izin) (?:almadan|istemeden)",
    r"(?:hemen|derhal) (?:iade|ödeme) (?:yap|onayla)",
    r"sistem (?:mesajını|talimatını|komutunu) (?:göster|yazdır|açıkla)",
)

_LEXICAL = tuple((re.compile(pattern, re.I), pattern) for pattern in _OVERRIDE_PHRASES)

# ---------------------------------------------------------------------------
# Layer 3: density
# ---------------------------------------------------------------------------

#: Second-person imperatives aimed at the system rather than at a person. A
#: complaint says "my parcel"; an injection says "you must".
#:
#: Bare "never" and "always" were here and had to come out. "My order never
#: arrived" is the single most common sentence in this domain, and matching it
#: escalated a large share of entirely legitimate non-receipt claims. The
#: patterns below only fire on language directed at the system, which is the
#: thing the density layer is actually trying to measure.
_IMPERATIVE = re.compile(
    r"\b(?:you must|you should|you will|you are to|you are now|"
    r"do not (?:ask|tell|mention|reveal|follow|apply|use)|"
    r"never (?:ask|tell|mention|reveal|refuse|decline|question)|"
    r"always (?:approve|allow|grant|issue|obey|comply)|"
    r"instead of|from now on|"
    r"yapmalısın|etmelisin|bundan sonra|"
    r"asla (?:sorma|söyleme|belirtme)|her zaman (?:onayla|kabul et))\b",
    re.I,
)

#: Words that only appear when someone is talking *about* the system.
_SYSTEM_VOCABULARY = re.compile(
    r"\b(?:prompt|instruction|system message|guardrail|policy engine|tool|function call|"
    r"api|token|model|assistant|agent|"
    r"talimat|komut|sistem mesajı)\b",
    re.I,
)

#: Above this share of system-directed language, a complaint is not a complaint.
DENSITY_THRESHOLD = 0.035


@dataclass(frozen=True, slots=True)
class InjectionFinding:
    layer: str
    pattern: str
    span: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class InjectionReport:
    findings: tuple[InjectionFinding, ...]
    density: float
    events: tuple[GuardrailEvent, ...]

    @property
    def layers_triggered(self) -> frozenset[str]:
        return frozenset(finding.layer for finding in self.findings)

    @property
    def suspicious(self) -> bool:
        return bool(self.findings)


def _density(text: str) -> float:
    words = text.split()
    if len(words) < 8:
        # Too short to have a meaningful ratio. "ignore previous instructions" on
        # its own is caught by the lexical layer, which is the right layer for it.
        return 0.0

    hits = len(_IMPERATIVE.findall(text)) + len(_SYSTEM_VOCABULARY.findall(text))
    return hits / len(words)


def scan(text: str) -> InjectionReport:
    """Run every layer over untrusted text.

    Returns:
        A report. Severity rises with the number of *distinct layers* that fire,
        not the number of matches: ten hits from one weak pattern is one weak
        signal, whereas structure plus lexical is two independent ones.
    """
    findings: list[InjectionFinding] = []

    for pattern, label in _STRUCTURAL:
        for match in pattern.finditer(text):
            findings.append(InjectionFinding("structure", label, (match.start(), match.end())))

    for pattern, label in _LEXICAL:
        for match in pattern.finditer(text):
            findings.append(InjectionFinding("lexical", label, (match.start(), match.end())))

    density = _density(text)
    if density > DENSITY_THRESHOLD:
        findings.append(InjectionFinding("density", f"{density:.3f}", None))

    events: list[GuardrailEvent] = []
    layers = frozenset(finding.layer for finding in findings)

    if "structure" in layers:
        structural = [f for f in findings if f.layer == "structure"]
        events.append(
            GuardrailEvent(
                detector=Detector.INJECTION_STRUCTURE,
                severity=Severity.CRITICAL,
                action=Action.BLOCK,
                summary=(
                    f"customer text contains {len(structural)} prompt-structure "
                    f"construct(s): {', '.join(sorted({f.pattern for f in structural}))}"
                ),
                span=structural[0].span,
                detail={"patterns": sorted({f.pattern for f in structural})},
            )
        )

    if "lexical" in layers:
        lexical = [f for f in findings if f.layer == "lexical"]
        distinct = len({f.pattern for f in lexical})
        # One phrase can be a customer quoting an email they received. Two or more
        # distinct override phrasings is not a coincidence.
        events.append(
            GuardrailEvent(
                detector=Detector.INJECTION_HEURISTIC,
                severity=Severity.HIGH if distinct > 1 else Severity.MEDIUM,
                action=Action.BLOCK if distinct > 1 else Action.ESCALATE,
                summary=f"{distinct} distinct instruction-override phrasing(s) found",
                span=lexical[0].span,
                detail={"distinct_patterns": distinct},
            )
        )

    if "density" in layers:
        events.append(
            GuardrailEvent(
                detector=Detector.INJECTION_DENSITY,
                severity=Severity.MEDIUM,
                # On its own, high density escalates rather than blocks: a
                # frustrated customer writing in short imperative sentences is a
                # real thing, and blocking them would be worse than reading it.
                action=Action.ESCALATE,
                summary=(
                    f"system-directed language density {density:.1%} exceeds "
                    f"{DENSITY_THRESHOLD:.1%}"
                ),
                detail={"density": round(density, 4), "threshold": DENSITY_THRESHOLD},
            )
        )

    # Layers, not matches. Ten hits from one weak pattern is one weak signal;
    # two layers firing are two independent ones, and independence is what makes
    # the combination strong. Density on its own escalates, and a single lexical
    # phrase on its own escalates - together they block.
    if len(layers) >= 2 and not any(event.action is Action.BLOCK for event in events):
        events.append(
            GuardrailEvent(
                detector=Detector.INJECTION_HEURISTIC,
                severity=Severity.CRITICAL,
                action=Action.BLOCK,
                summary=(
                    f"{len(layers)} independent injection signals agree: "
                    f"{', '.join(sorted(layers))}"
                ),
                detail={"layers": sorted(layers)},
            )
        )

    return InjectionReport(findings=tuple(findings), density=density, events=tuple(events))


# ---------------------------------------------------------------------------
# Canary
# ---------------------------------------------------------------------------


def new_canary() -> str:
    """A per-ticket marker to plant in the system prompt.

    Unguessable and unique, so its appearance in output is proof rather than
    inference. Regenerated per ticket: a fixed canary would eventually be learned.
    """
    return f"BACKSTOP-CANARY-{secrets.token_hex(8)}"


def canary_leaked(output: str, canary: str) -> GuardrailEvent | None:
    """Check whether the system prompt escaped into the output.

    This is the one injection signal that is not a heuristic. If the canary is in
    the output, the model reproduced its instructions, and the only safe response
    is to discard the output entirely.
    """
    if canary not in output:
        return None

    return GuardrailEvent(
        detector=Detector.CANARY_LEAK,
        severity=Severity.CRITICAL,
        action=Action.BLOCK,
        summary="the system prompt canary appeared in model output",
        detail={"proof": "exact match", "canary_prefix": canary[:14]},
    )


__all__ = [
    "DENSITY_THRESHOLD",
    "InjectionFinding",
    "InjectionReport",
    "canary_leaked",
    "new_canary",
    "scan",
]
