"""Normalisation, before any detector runs.

Detectors match patterns. An attacker who can change the bytes without changing
what a model reads defeats every pattern at once, so normalisation has to come
first and has to be the *same* normalisation the model effectively sees.

Three classes of trick this handles:

**Invisible characters.** ``ig\\u200bnore previous instructions`` reads as "ignore"
to a tokenizer and matches nothing. Zero-width spaces, joiners, soft hyphens and
bidi controls are stripped.

**Confusables.** Cyrillic ``а`` (U+0430) renders identically to Latin ``a``. NFKC
handles some of this; the explicit map handles the rest.

**Volume.** A megabyte of text is not a complaint, it is either a mistake or an
attempt to push the real instructions out of a context window. Length is capped
before anything else touches the string.

The normalised text is what gets stored and processed. The original is kept
alongside it, because an audit record of what the customer *actually sent* is not
optional - and because the difference between the two is itself a signal.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from backstop_guardrails.events import Action, Detector, GuardrailEvent, Severity

#: Beyond this a ticket is not a complaint. Generous enough for a genuinely
#: furious customer with a long order history to quote.
MAX_LENGTH = 8000

#: Stripped outright. Every one of these is invisible and none belongs in a
#: customer's message.
_INVISIBLE = frozenset(
    "​‌‍⁠﻿­᠎"  # zero-width and soft hyphen
    "‪‫‬‭‮"  # bidi overrides
    "⁦⁧⁨⁩"  # bidi isolates
)

#: Homoglyphs NFKC does not fold. Cyrillic and Greek letters that render as Latin.
_CONFUSABLES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
        "ѕ": "s",
        "і": "i",
        "ј": "j",
        "ԁ": "d",
        "ᴏ": "o",
        "ο": "o",
        "α": "a",
        "ρ": "p",
        "τ": "t",
        "ν": "v",
        "κ": "k",
    }
)


@dataclass(frozen=True, slots=True)
class Normalised:
    """The cleaned text, the original, and what changed."""

    text: str
    original: str
    events: tuple[GuardrailEvent, ...]

    @property
    def was_modified(self) -> bool:
        return self.text != self.original


def normalise(raw: str, *, max_length: int = MAX_LENGTH) -> Normalised:
    """Clean untrusted text and report what had to be cleaned.

    Args:
        raw: Text exactly as received.
        max_length: Truncation point.

    Returns:
        The normalised text plus events describing every change. A change is
        always reported: silently rewriting a customer's words and then acting on
        the rewrite is indefensible in an audit.
    """
    events: list[GuardrailEvent] = []
    text = raw

    if len(text) > max_length:
        events.append(
            GuardrailEvent(
                detector=Detector.LENGTH,
                severity=Severity.HIGH,
                # Escalate rather than annotate. Truncation defeats a padding
                # attack, but it also means a person never saw the part that was
                # cut - and the part that was cut is where the payload would be.
                action=Action.ESCALATE,
                summary=f"input truncated from {len(text)} to {max_length} characters",
                detail={"original_length": len(text), "max_length": max_length},
            )
        )
        text = text[:max_length]

    invisible_count = sum(1 for char in text if char in _INVISIBLE)
    if invisible_count:
        events.append(
            GuardrailEvent(
                detector=Detector.ENCODING,
                severity=Severity.HIGH,
                action=Action.ANNOTATE,
                summary=f"{invisible_count} invisible character(s) removed",
                # Invisible characters do not arrive by accident. Their presence
                # is itself evidence, so the count is recorded even though the
                # text is cleaned and processing continues.
                detail={"count": invisible_count, "reason": "zero-width or bidi control"},
            )
        )
        text = "".join(char for char in text if char not in _INVISIBLE)

    folded = text.translate(_CONFUSABLES)
    if folded != text:
        changed = sum(1 for before, after in zip(text, folded, strict=True) if before != after)
        events.append(
            GuardrailEvent(
                detector=Detector.ENCODING,
                severity=Severity.HIGH,
                action=Action.ANNOTATE,
                summary=f"{changed} homoglyph(s) folded to their Latin equivalents",
                detail={"count": changed},
            )
        )
        text = folded

    # NFKC last: it settles compatibility forms (fullwidth, ligatures, circled
    # letters) that the explicit map above does not enumerate.
    composed = unicodedata.normalize("NFKC", text)
    if composed != text:
        events.append(
            GuardrailEvent(
                detector=Detector.ENCODING,
                severity=Severity.LOW,
                action=Action.ANNOTATE,
                summary="text required Unicode NFKC normalisation",
            )
        )
        text = composed

    # Collapse runs of whitespace but keep paragraph structure: a wall of blank
    # lines is a padding technique, and losing paragraphs loses meaning.
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return Normalised(text=text, original=raw, events=tuple(events))


__all__ = ["MAX_LENGTH", "Normalised", "normalise"]
