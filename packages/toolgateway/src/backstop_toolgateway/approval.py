"""Human approval as a bearer token bound to one specific action.

The naive design is a boolean: a human clicks approve, the graph sets
``approved = True``, the gateway lets the call through. That fails in three ways
this project cares about.

1. **Replay.** An approval for a EUR 20 refund is reused for a EUR 2,000 one.
2. **Confusion.** An approval granted on one ticket authorises a call on another.
3. **Deniability.** Nothing in the record proves who approved what, or that the
   arguments at execution time are the arguments the approver saw.

So an approval is a signed token bound to the ticket, the tool, and a digest of
the exact arguments. Change any of them and the binding no longer matches. The
token also carries an amount ceiling, so an approver who saw EUR 20 cannot be made
to have authorised more.

The signature is HMAC-SHA256 with a server-side secret. That is the right
primitive here: the issuer and the verifier are the same system, so there is no
need for asymmetric keys, and a MAC has no misuse footguns of the kind signature
verification usually offers.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from backstop_toolgateway.canonical import Clock, canonical_json, digest, system_clock
from backstop_toolgateway.errors import ApprovalInvalid

#: How long an approval stays usable. Short: an approver's judgement is about the
#: situation in front of them, and situations change.
DEFAULT_TTL = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    """A human decision, bound to one action."""

    ticket_id: str
    tool: str
    args_digest: str
    approver: str
    issued_at: datetime
    expires_at: datetime
    max_amount: Decimal | None
    signature: str

    def binding(self) -> dict[str, Any]:
        """The signed material. Everything that makes this token specific."""
        return {
            "ticket_id": self.ticket_id,
            "tool": self.tool,
            "args_digest": self.args_digest,
            "approver": self.approver,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_amount": self.max_amount,
        }

    def redacted(self) -> dict[str, Any]:
        """Form safe to place in an audit entry: identity without the secret."""
        return {
            "approver": self.approver,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "max_amount": str(self.max_amount) if self.max_amount is not None else None,
            "signature_prefix": self.signature[:12],
        }


class ApprovalAuthority:
    """Issues and verifies approval tokens."""

    def __init__(self, secret: str, *, clock: Clock = system_clock, ttl: timedelta = DEFAULT_TTL):
        if len(secret) < 16:
            raise ValueError("approval secret must be at least 16 characters")
        self._secret = secret.encode("utf-8")
        self._clock = clock
        self._ttl = ttl

    def _sign(self, binding: Mapping[str, Any]) -> str:
        return hmac.new(self._secret, canonical_json(binding).encode("utf-8"), sha256).hexdigest()

    def issue(
        self,
        *,
        ticket_id: str,
        tool: str,
        args: Mapping[str, Any],
        approver: str,
        max_amount: Decimal | None = None,
    ) -> ApprovalToken:
        """Mint a token for exactly these arguments."""
        now = self._clock().astimezone(UTC)
        partial = {
            "ticket_id": ticket_id,
            "tool": tool,
            "args_digest": digest(args),
            "approver": approver,
            "issued_at": now,
            "expires_at": now + self._ttl,
            "max_amount": max_amount,
        }
        return ApprovalToken(
            ticket_id=ticket_id,
            tool=tool,
            args_digest=str(partial["args_digest"]),
            approver=approver,
            issued_at=now,
            expires_at=now + self._ttl,
            max_amount=max_amount,
            signature=self._sign(partial),
        )

    def verify(
        self,
        token: ApprovalToken,
        *,
        ticket_id: str,
        tool: str,
        args: Mapping[str, Any],
        amount: Decimal | None = None,
    ) -> None:
        """Check a token authorises this exact call.

        Raises:
            ApprovalInvalid: on a bad signature, expiry, a binding mismatch, or an
                amount above what the approver authorised.
        """
        expected = self._sign(token.binding())
        # Constant-time comparison. The window is small but the habit is not
        # optional in code that gates money movement.
        if not hmac.compare_digest(expected, token.signature):
            raise ApprovalInvalid("approval signature does not verify", tool=tool)

        now = self._clock().astimezone(UTC)
        if now >= token.expires_at:
            raise ApprovalInvalid(f"approval expired at {token.expires_at.isoformat()}", tool=tool)

        if token.ticket_id != ticket_id:
            raise ApprovalInvalid(
                f"approval is bound to ticket {token.ticket_id}, not {ticket_id}", tool=tool
            )

        if token.tool != tool:
            raise ApprovalInvalid(f"approval is bound to tool {token.tool}, not {tool}", tool=tool)

        if token.args_digest != digest(args):
            raise ApprovalInvalid("arguments changed after approval was granted", tool=tool)

        if token.max_amount is not None and amount is not None and amount > token.max_amount:
            raise ApprovalInvalid(
                f"approval covers up to {token.max_amount}, call requests {amount}", tool=tool
            )


__all__ = ["DEFAULT_TTL", "ApprovalAuthority", "ApprovalToken"]
