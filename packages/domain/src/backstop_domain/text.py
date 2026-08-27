"""Turkish-aware text normalisation.

Python's default casing rules mishandle Turkish. ``"İ".lower()`` produces ``"i"``
followed by a combining dot above (U+0307) rather than a plain ``"i"``, and
``"I".lower()`` produces ``"i"`` where Turkish orthography wants ``"ı"``. Left
alone, that turns one address into two and one customer name into two, which
quietly breaks both the address-reuse fraud signal and any deduplication built on
top of it.

Everything that needs a comparable form of a Turkish string goes through
:func:`fold` here, so the rules live in one place. The guardrail plane will reuse
this when it normalises input before running PII detection.
"""

from __future__ import annotations

#: Applied *before* lowercasing, so that the uppercase Turkish letters never reach
#: Python's default casing rules.
_TURKISH_FOLD = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "Ç": "c",
        "Ğ": "g",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)


def fold(value: str) -> str:
    """Return a lowercase ASCII-folded form suitable for comparison.

    Not a transliteration for display - it deliberately collapses ``ı`` and ``i``
    onto the same character so that two spellings of one address match.
    """
    return value.translate(_TURKISH_FOLD).lower()


def slug(value: str) -> str:
    """Folded form reduced to alphanumerics. Used for emails and identifiers."""
    return "".join(char for char in fold(value) if char.isalnum())


def fingerprint(*parts: str) -> str:
    """Stable comparison key built from several fields.

    Parts are folded, stripped of non-alphanumerics and joined with ``|`` so that
    an empty field cannot silently merge two different keys.
    """
    return "|".join(slug(part) for part in parts)


__all__ = ["fingerprint", "fold", "slug"]
