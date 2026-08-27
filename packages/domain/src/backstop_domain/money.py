"""Monetary amounts.

A refund system that stores money in a binary float will, eventually, refund the
wrong number. Everything monetary in Backstop is a ``Decimal`` quantised to two
places with banker's rounding turned off in favour of ``ROUND_HALF_UP``, which is
what a customer and an accountant both expect.

``Money`` is the annotated type to use in models: it coerces strings, integers and
floats into a quantised ``Decimal`` and rejects anything that cannot be an amount.
Floats are accepted because JSON fixtures produce them, but they are routed
through ``str`` first so that ``0.1 + 0.2`` never becomes ``0.30000000000000004``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer

CENTS = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Coerce a value into a two-place ``Decimal``.

    Raises:
        ValueError: if the value cannot represent an amount.
    """
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, float):
        # repr round-trips the shortest exact representation, which is the
        # number the author of the fixture actually meant.
        candidate = Decimal(repr(value))
    elif isinstance(value, int | str):
        try:
            candidate = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{value!r} is not a monetary amount") from exc
    else:
        raise ValueError(f"{type(value).__name__} cannot be a monetary amount")

    if not candidate.is_finite():
        raise ValueError("monetary amounts must be finite")

    return candidate.quantize(CENTS, rounding=ROUND_HALF_UP)


Money = Annotated[
    Decimal,
    BeforeValidator(money),
    Field(ge=0, description="Amount in the order currency, two decimal places"),
    # Serialised as a string so that a JSON round-trip cannot reintroduce a float.
    PlainSerializer(str, return_type=str, when_used="json"),
]

SignedMoney = Annotated[
    Decimal,
    BeforeValidator(money),
    Field(description="Amount that may be negative, two decimal places"),
    PlainSerializer(str, return_type=str, when_used="json"),
]

__all__ = ["CENTS", "Money", "SignedMoney", "money"]
