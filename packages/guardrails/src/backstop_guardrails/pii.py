"""Personal data: find it, replace it, and put it back only where allowed.

The design is tokenisation, not redaction. ``Ayşe Yılmaz`` becomes ``<PERSON_1>``
and the mapping is held in a vault outside the model's reach. The model reasons
about ``<PERSON_1>``, writes a reply that says ``<PERSON_1>``, and the placeholder
is resolved back to the name only when the reply leaves through a channel
authorised to see it.

Redaction - replacing with ``[REDACTED]`` - would be simpler and would break the
product: the reply has to be able to address the customer by name.

Three properties the vault guarantees:

* **Stable within a ticket.** The same value always maps to the same placeholder,
  so a model can tell that the person who ordered and the person complaining are
  the same person.
* **Not stable across tickets.** ``<PERSON_1>`` in one ticket has nothing to do
  with ``<PERSON_1>`` in another, so placeholders cannot be correlated.
* **Never inside a prompt.** The vault lives beside the graph state, not in it.

The detectors are written here rather than pulled from a library on purpose. The
Turkish identifiers - TCKN, IBAN - have checksums, and validating them removes
almost all of the false positives that a bare eleven-digit-number pattern would
produce on an order reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from backstop_domain.text import fold
from backstop_guardrails.events import Action, Detector, GuardrailEvent, Severity


class PIIKind(StrEnum):
    PERSON = "PERSON"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    TCKN = "TCKN"
    IBAN = "IBAN"
    CARD = "CARD"
    ADDRESS = "ADDRESS"

    @property
    def severity(self) -> Severity:
        # A national identity number or a bank account in a support ticket is a
        # different order of problem from a name.
        return {
            PIIKind.TCKN: Severity.CRITICAL,
            PIIKind.IBAN: Severity.CRITICAL,
            PIIKind.CARD: Severity.CRITICAL,
            PIIKind.EMAIL: Severity.MEDIUM,
            PIIKind.PHONE: Severity.MEDIUM,
            PIIKind.ADDRESS: Severity.MEDIUM,
            PIIKind.PERSON: Severity.LOW,
        }[self]


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def is_valid_tckn(value: str) -> bool:
    """Turkish national identity number checksum.

    Eleven digits, first non-zero, with two check digits. Without this check the
    pattern would match order references and phone numbers constantly.
    """
    if len(value) != 11 or not value.isdigit() or value[0] == "0":
        return False

    digits = [int(char) for char in value]
    odd_sum = sum(digits[0:9:2])
    even_sum = sum(digits[1:8:2])

    tenth = (odd_sum * 7 - even_sum) % 10
    eleventh = sum(digits[:10]) % 10

    return digits[9] == tenth and digits[10] == eleventh


def is_valid_iban(value: str) -> bool:
    """ISO 13616 mod-97 check."""
    compact = value.replace(" ", "").upper()
    if len(compact) < 15 or len(compact) > 34 or not compact[:2].isalpha():
        return False

    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) if char.isalpha() else char for char in rearranged)
    if not numeric.isdigit():
        return False

    return int(numeric) % 97 == 1


def is_valid_card(value: str) -> bool:
    """Luhn check."""
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False

    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_TCKN = re.compile(r"\b\d{11}\b")
_IBAN = re.compile(r"\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"(?:\+90|0)?[\s.-]?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}\b")
_ADDRESS = re.compile(
    r"\b[\wçğıöşüÇĞİÖŞÜ]+\s+(?:Caddesi|Cadde|Cad\.|Sokak|Sok\.|Bulvarı|Bulvar|Mahallesi|Mah\.)"
    r"(?:\s+No\s*:?\s*\d+(?:/\d+)?)?",
    re.IGNORECASE,
)

#: Order, shipment and product references look like identifiers but are not
#: personal data. Matched first so they are never tokenised.
_ALLOWLIST = re.compile(r"\b(?:ORD|SHP|CUS|RET)-\d+\b|\bSKU-[A-Z]{3}-\d{4}\b")


@dataclass(frozen=True, slots=True)
class PIIMatch:
    kind: PIIKind
    start: int
    end: int
    value: str


@dataclass(slots=True)
class Vault:
    """Placeholder to original value, for one ticket.

    Lives beside the graph state and is never serialised into a prompt. The graph
    carries the vault; the model carries only placeholders.
    """

    ticket_id: str
    mapping: dict[str, str] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)
    _counters: dict[PIIKind, int] = field(default_factory=dict)

    def placeholder_for(self, kind: PIIKind, value: str) -> str:
        if value in self._reverse:
            return self._reverse[value]

        self._counters[kind] = self._counters.get(kind, 0) + 1
        token = f"<{kind.value}_{self._counters[kind]}>"
        self.mapping[token] = value
        self._reverse[value] = token
        return token

    def resolve(self, text: str) -> str:
        """Substitute placeholders back. Only ever called for an authorised channel."""
        for token, value in self.mapping.items():
            text = text.replace(token, value)
        return text

    def unresolved_tokens(self, text: str) -> tuple[str, ...]:
        """Placeholders still present. Used by the output leak scan."""
        return tuple(token for token in self.mapping if token in text)

    def __len__(self) -> int:
        return len(self.mapping)


@dataclass(frozen=True, slots=True)
class Tokenised:
    text: str
    vault: Vault
    matches: tuple[PIIMatch, ...]
    events: tuple[GuardrailEvent, ...]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect(text: str, *, known_names: frozenset[str] | None = None) -> list[PIIMatch]:
    """Find personal data.

    Order matters: the most specific and most strongly validated patterns run
    first and claim their spans, so a card number is never also reported as a
    phone number.

    Args:
        text: Normalised text.
        known_names: Optional gazetteer of given and family names. Person
            detection without one is guesswork; with one it is a lookup. Real
            deployments source this from the customer directory.
    """
    protected: list[tuple[int, int]] = [
        (match.start(), match.end()) for match in _ALLOWLIST.finditer(text)
    ]
    matches: list[PIIMatch] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < other_end and end > other_start for other_start, other_end in protected)

    def claim(kind: PIIKind, start: int, end: int, value: str) -> None:
        if overlaps(start, end):
            return
        protected.append((start, end))
        matches.append(PIIMatch(kind=kind, start=start, end=end, value=value))

    for match in _IBAN.finditer(text):
        if is_valid_iban(match.group()):
            claim(PIIKind.IBAN, match.start(), match.end(), match.group())

    for match in _CARD.finditer(text):
        if is_valid_card(match.group()):
            claim(PIIKind.CARD, match.start(), match.end(), match.group())

    for match in _TCKN.finditer(text):
        if is_valid_tckn(match.group()):
            claim(PIIKind.TCKN, match.start(), match.end(), match.group())

    for match in _EMAIL.finditer(text):
        claim(PIIKind.EMAIL, match.start(), match.end(), match.group())

    for match in _PHONE.finditer(text):
        digits = sum(1 for char in match.group() if char.isdigit())
        if digits >= 10:
            claim(PIIKind.PHONE, match.start(), match.end(), match.group())

    for match in _ADDRESS.finditer(text):
        claim(PIIKind.ADDRESS, match.start(), match.end(), match.group())

    if known_names:
        # Turkish folding, not casefold. Someone typing "Ayse Yilmaz" on a keyboard
        # without Turkish characters is the same person as "Ayşe Yılmaz" in the
        # directory. casefold treats them as two different names, which leaves the
        # ASCII spelling untokenised and sends it straight into a prompt.
        folded_names = {fold(name) for name in known_names}
        for match in re.finditer(r"\b[^\W\d_]{2,}\b", text, re.UNICODE):
            if fold(match.group()) in folded_names:
                claim(PIIKind.PERSON, match.start(), match.end(), match.group())

    matches.sort(key=lambda item: item.start)
    return matches


def tokenise(
    text: str,
    *,
    ticket_id: str,
    known_names: frozenset[str] | None = None,
    vault: Vault | None = None,
) -> Tokenised:
    """Replace personal data with stable placeholders.

    Returns:
        The tokenised text, the vault holding the mapping, and one event per kind
        found. Events carry counts and never the values themselves - putting the
        matched value in the event would defeat the entire exercise.
    """
    vault = vault or Vault(ticket_id=ticket_id)
    matches = detect(text, known_names=known_names)

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start])
        pieces.append(vault.placeholder_for(match.kind, match.value))
        cursor = match.end
    pieces.append(text[cursor:])

    counts: dict[PIIKind, int] = {}
    for match in matches:
        counts[match.kind] = counts.get(match.kind, 0) + 1

    events = tuple(
        GuardrailEvent(
            detector=Detector.PII,
            severity=kind.severity,
            action=(
                Action.ESCALATE
                if kind in (PIIKind.TCKN, PIIKind.IBAN, PIIKind.CARD)
                else Action.ANNOTATE
            ),
            summary=f"{count} {kind.value.lower()} value(s) tokenised",
            detail={"kind": kind.value, "count": count},
        )
        for kind, count in sorted(counts.items(), key=lambda item: item[0].value)
    )

    return Tokenised(text="".join(pieces), vault=vault, matches=tuple(matches), events=events)


def turkish_name_gazetteer() -> frozenset[str]:
    """Given and family names from the synthetic customer base.

    A real deployment builds this from its customer directory. Using the same
    source the dataset was generated from keeps the labs honest: the names in a
    ticket are names the system could plausibly know.
    """
    from backstop_domain.generator import _FAMILY_NAMES, _GIVEN_NAMES

    return frozenset(_GIVEN_NAMES) | frozenset(_FAMILY_NAMES)


__all__ = [
    "PIIKind",
    "PIIMatch",
    "Tokenised",
    "Vault",
    "detect",
    "is_valid_card",
    "is_valid_iban",
    "is_valid_tckn",
    "tokenise",
    "turkish_name_gazetteer",
]
