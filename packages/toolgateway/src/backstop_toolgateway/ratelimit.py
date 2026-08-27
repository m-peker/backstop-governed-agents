"""Rate limiting.

A token bucket per ``(principal, tool)``. The limit is not primarily an
anti-abuse control here - the principals are our own agents - it is a containment
control. An agent stuck in a loop, or one steered into hammering a tool, is
stopped at the boundary rather than after it has made ten thousand calls.

Time is injected. A rate limiter that reads the wall clock is a rate limiter whose
tests either sleep or flake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backstop_toolgateway.canonical import Clock, system_clock


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: datetime
    capacity: float
    refill_per_second: float = field(default=0.0)

    def take(self, now: datetime) -> tuple[bool, float]:
        """Attempt to spend one token.

        Returns:
            ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is zero
            when the call was allowed.
        """
        elapsed = max((now - self.updated_at).total_seconds(), 0.0)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0

        deficit = 1.0 - self.tokens
        retry_after = deficit / self.refill_per_second if self.refill_per_second else float("inf")
        return False, round(retry_after, 3)


class RateLimiter:
    """Token buckets keyed by principal and tool."""

    def __init__(self, *, clock: Clock = system_clock) -> None:
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def check(self, *, principal: str, tool: str, per_minute: int) -> tuple[bool, float]:
        """Spend one token for this principal and tool.

        A bucket starts full, so the first call after a quiet period is never
        delayed - the limit shapes sustained rate, not the first request.
        """
        if per_minute <= 0:
            return False, float("inf")

        now = self._clock().astimezone(UTC)
        key = (principal, tool)
        bucket = self._buckets.get(key)

        if bucket is None:
            bucket = _Bucket(
                tokens=float(per_minute),
                updated_at=now,
                capacity=float(per_minute),
                refill_per_second=per_minute / 60.0,
            )
            self._buckets[key] = bucket

        return bucket.take(now)

    def reset(self) -> None:
        self._buckets.clear()


__all__ = ["RateLimiter"]
