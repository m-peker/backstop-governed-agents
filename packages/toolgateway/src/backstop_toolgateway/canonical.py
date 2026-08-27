"""Canonical serialisation, digests and the injected clock.

Three small things that everything else in the gateway depends on.

**Canonical JSON.** Idempotency keys, approval-token bindings and the audit hash
chain all hash structured data. If two logically identical payloads serialise
differently - keys in another order, a float rendered with a different precision -
the hashes diverge and every guarantee built on them evaporates. So there is
exactly one serialisation, defined here, and nothing hashes JSON any other way.

**Digests.** SHA-256 over the canonical form, hex encoded.

**The clock.** Time is injected, never read from the module. Rate limits, token
expiry and audit timestamps are all time-dependent, and a test that cannot control
time either sleeps or is flaky.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

#: A callable returning the current time. Injected everywhere it is needed.
Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """Wall clock in UTC. The default outside tests."""
    return datetime.now(UTC)


class FixedClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)
        return self._now


class SupportsCanonical(Protocol):
    def model_dump(self, **kwargs: Any) -> dict[str, Any]: ...


def _default(value: Any) -> Any:
    """Render types ``json`` cannot, in a form that is stable across runs."""
    if isinstance(value, Decimal):
        # str() preserves the exact scale, which matters: Decimal("10.00") and
        # Decimal("10") are the same amount but must not hash the same, because
        # one of them came from a two-place quantisation and the other did not.
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"{type(value).__name__} is not canonically serialisable")


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace, UTF-8 text.

    ``ensure_ascii`` is off so that Turkish characters survive as themselves
    rather than as escapes - the audit log is meant to be readable by a person.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    )


def digest(payload: Any) -> str:
    """SHA-256 of the canonical form, hex encoded."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chain_hash(previous: str, payload: Any) -> str:
    """Link one audit entry to the one before it.

    The previous hash is folded in with a separator that cannot occur in a hex
    digest, so that no concatenation of two different (previous, payload) pairs
    can produce the same input string.
    """
    material = f"{previous}\n{canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


#: Hash standing in for "nothing came before this". The genesis link.
GENESIS_HASH = "0" * 64


__all__ = [
    "GENESIS_HASH",
    "Clock",
    "FixedClock",
    "canonical_json",
    "chain_hash",
    "digest",
    "system_clock",
]
