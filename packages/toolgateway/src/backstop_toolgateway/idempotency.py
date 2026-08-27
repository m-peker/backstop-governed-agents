"""Idempotency.

The failure this prevents is specific and it is the reason the gateway exists.

A LangGraph node calls ``issue_refund``. The refund succeeds. The process dies
before the checkpoint is written. On restart the graph replays from the last
checkpoint and calls ``issue_refund`` again. The customer is refunded twice.

Retries make it worse, not better: a timeout on a call that actually succeeded is
indistinguishable, from the caller's side, from one that failed.

So the gateway derives a key from ``(ticket_id, tool, canonical(args))`` and
remembers the outcome. A second call bearing the same key never reaches the
handler; the stored result is returned and the audit chain records a ``replayed``
entry, so the replay is visible rather than silent.

The key is derived, not supplied. A caller-provided key can be got wrong - or, in
this threat model, got wrong on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from backstop_toolgateway.canonical import Clock, digest, system_clock

#: How long a result stays replayable. Long enough to cover a crash, a restart and
#: a human approval round trip; short enough that a genuinely new refund for the
#: same amount on the same ticket next month is not swallowed as a duplicate.
DEFAULT_RETENTION = timedelta(hours=24)


def idempotency_key(*, ticket_id: str, tool: str, args: dict[str, Any]) -> str:
    """Derive the key. Same ticket, same tool, same arguments, same key."""
    return digest({"ticket_id": ticket_id, "tool": tool, "args": args})


@dataclass(frozen=True, slots=True)
class StoredResult:
    key: str
    tool: str
    ticket_id: str
    result: Any
    stored_at: datetime

    def is_expired(self, *, now: datetime, retention: timedelta) -> bool:
        return now - self.stored_at > retention


class IdempotencyStore(Protocol):
    """Where completed write results are remembered."""

    def get(self, key: str) -> StoredResult | None: ...

    def put(self, key: str, *, ticket_id: str, tool: str, result: Any) -> StoredResult: ...


class MemoryIdempotencyStore:
    """In-process store.

    Correct for a single process, which is what the tests and the labs run. Phase
    2 swaps in the Redis-backed implementation, where the guarantee has to survive
    several API workers - and where the store must additionally reserve the key
    *before* the handler runs, so two concurrent replays cannot both miss.
    """

    def __init__(
        self, *, clock: Clock = system_clock, retention: timedelta = DEFAULT_RETENTION
    ) -> None:
        self._clock = clock
        self._retention = retention
        self._entries: dict[str, StoredResult] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> StoredResult | None:
        stored = self._entries.get(key)
        if stored is None:
            return None
        if stored.is_expired(now=self._clock().astimezone(UTC), retention=self._retention):
            del self._entries[key]
            return None
        return stored

    def put(self, key: str, *, ticket_id: str, tool: str, result: Any) -> StoredResult:
        stored = StoredResult(
            key=key,
            tool=tool,
            ticket_id=ticket_id,
            result=result,
            stored_at=self._clock().astimezone(UTC),
        )
        self._entries[key] = stored
        return stored


__all__ = [
    "DEFAULT_RETENTION",
    "IdempotencyStore",
    "MemoryIdempotencyStore",
    "StoredResult",
    "idempotency_key",
]
