"""The audit chain.

Every gateway invocation appends an entry, whether it succeeded, was refused, or
raised. Each entry carries the hash of the one before it, so removing or editing a
past entry invalidates every hash after it. That is what "tamper-evident" buys:
not prevention, but detection - an operator with database access can still delete
a row, they simply cannot do it without the chain saying so.

Two rules the entries obey.

**Arguments are stored as a digest, not in the clear.** Tool arguments contain
order identifiers and amounts, and in a system that handles personal data an audit
log that copies every payload becomes its own disclosure problem. The digest
proves *which* arguments were used to anyone who has them; it does not hand them
to anyone who reads the log.

**Refusals are recorded as carefully as successes.** An attacker probing the tool
surface produces a long run of ``scope_denied`` entries, and that run is the
signal. A log that only records what worked would show nothing at all.

This is the in-memory implementation, sufficient for the gateway and its tests.
Phase 6 adds the Postgres sink, the verifier CLI and the per-ticket dossier export
on top of the same entry shape.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backstop_toolgateway.canonical import GENESIS_HASH, Clock, chain_hash, digest, system_clock


class Outcome(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    FAILED = "failed"
    REPLAYED = "replayed"
    """The call matched an earlier idempotency key; the stored result was returned."""


class AuditEntry(BaseModel):
    """One immutable record of one attempted capability use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=0)
    at: datetime
    ticket_id: str
    principal: str
    tool: str
    scope: str
    outcome: Outcome
    args_digest: str
    idempotency_key: str | None = None
    amount: Decimal | None = None
    approval: dict[str, Any] | None = None
    refusal_code: str | None = None
    detail: str = ""
    duration_ms: float | None = None

    previous_hash: str
    entry_hash: str

    def payload(self) -> dict[str, Any]:
        """The hashed material: everything except the hash fields themselves."""
        return self.model_dump(mode="json", exclude={"entry_hash", "previous_hash"})


class AuditChain:
    """Append-only, hash-linked sequence of audit entries."""

    def __init__(self, *, clock: Clock = system_clock) -> None:
        self._clock = clock
        self._entries: list[AuditEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self._entries)

    @property
    def head(self) -> str:
        """Hash of the most recent entry, or the genesis hash when empty."""
        return self._entries[-1].entry_hash if self._entries else GENESIS_HASH

    @property
    def entries(self) -> Sequence[AuditEntry]:
        return tuple(self._entries)

    def append(
        self,
        *,
        ticket_id: str,
        principal: str,
        tool: str,
        scope: str,
        outcome: Outcome,
        args: dict[str, Any],
        idempotency_key: str | None = None,
        amount: Decimal | None = None,
        approval: dict[str, Any] | None = None,
        refusal_code: str | None = None,
        detail: str = "",
        duration_ms: float | None = None,
    ) -> AuditEntry:
        previous = self.head

        # The hash is computed from the entry's own serialisation, never from a
        # parallel dict. Two serialisations of "the same" payload will eventually
        # diverge - a datetime rendered one way here and another way by the model
        # serialiser is enough - and the chain would then fail to verify against
        # data nobody touched. One source of truth, hashed once.
        draft = AuditEntry(
            sequence=len(self._entries),
            at=self._clock().astimezone(UTC),
            ticket_id=ticket_id,
            principal=principal,
            tool=tool,
            scope=scope,
            outcome=outcome,
            args_digest=digest(args),
            idempotency_key=idempotency_key,
            amount=amount,
            approval=approval,
            refusal_code=refusal_code,
            detail=detail,
            duration_ms=duration_ms,
            previous_hash=previous,
            entry_hash="",
        )
        entry = draft.model_copy(update={"entry_hash": chain_hash(previous, draft.payload())})

        self._entries.append(entry)
        return entry

    def verify(self) -> None:
        """Recompute the chain.

        Raises:
            ValueError: naming the first entry whose hash does not reconcile.
        """
        previous = GENESIS_HASH
        for position, entry in enumerate(self._entries):
            if entry.sequence != position:
                raise ValueError(f"entry at position {position} claims sequence {entry.sequence}")
            if entry.previous_hash != previous:
                raise ValueError(f"entry {entry.sequence} does not link to its predecessor")
            expected = chain_hash(previous, entry.payload())
            if expected != entry.entry_hash:
                raise ValueError(f"entry {entry.sequence} has been modified")
            previous = entry.entry_hash

    def for_ticket(self, ticket_id: str) -> tuple[AuditEntry, ...]:
        """Every entry for one ticket. The spine of a decision dossier."""
        return tuple(entry for entry in self._entries if entry.ticket_id == ticket_id)


__all__ = ["AuditChain", "AuditEntry", "Outcome"]
