"""Model pricing, normalised across providers.

Every provider bills differently - per million tokens, per thousand, with separate
rates for cached input - so the ledger would be meaningless without one place that
converts them all into USD.

These rates are a snapshot and will go stale. That is why :func:`cost_of` refuses
to guess: an unknown model raises rather than silently costing zero. A cost meter
that reports zero for the one model you actually deployed is worse than no cost
meter, because it looks like it is working.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backstop_llm.types import Usage

MILLION = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class Rate:
    """USD per million tokens."""

    input_usd: Decimal
    output_usd: Decimal
    #: Cached input is billed at a discount by most providers. When a provider
    #: does not distinguish it, this equals ``input_usd``.
    cached_input_usd: Decimal | None = None

    def cost(self, usage: Usage) -> Decimal:
        cached_rate = self.cached_input_usd if self.cached_input_usd is not None else self.input_usd
        fresh_input = max(usage.input_tokens - usage.cached_input_tokens, 0)

        total = (
            Decimal(fresh_input) * self.input_usd
            + Decimal(usage.cached_input_tokens) * cached_rate
            + Decimal(usage.output_tokens) * self.output_usd
        ) / MILLION

        # Six places, not two: a single classification can cost fractions of a
        # cent, and rounding those to zero would make the per-ticket total wrong
        # by the time a few hundred calls have accumulated.
        return total.quantize(Decimal("0.000001"))


#: Snapshot of published rates. Reviewed as part of the governance workflow rather
#: than edited casually, because the eval cost gate compares against these numbers.
RATES: dict[str, Rate] = {
    # OpenAI
    "gpt-4.1": Rate(Decimal("2.00"), Decimal("8.00"), Decimal("0.50")),
    "gpt-4.1-mini": Rate(Decimal("0.40"), Decimal("1.60"), Decimal("0.10")),
    "gpt-4.1-nano": Rate(Decimal("0.10"), Decimal("0.40"), Decimal("0.025")),
    "gpt-4o": Rate(Decimal("2.50"), Decimal("10.00"), Decimal("1.25")),
    "gpt-4o-mini": Rate(Decimal("0.15"), Decimal("0.60"), Decimal("0.075")),
    # Anthropic
    "claude-sonnet-5": Rate(Decimal("3.00"), Decimal("15.00"), Decimal("0.30")),
    "claude-opus-5": Rate(Decimal("15.00"), Decimal("75.00"), Decimal("1.50")),
    "claude-haiku-4-5-20251001": Rate(Decimal("1.00"), Decimal("5.00"), Decimal("0.10")),
    # Local models cost nothing to call. Electricity is somebody else's ledger.
    "ollama": Rate(Decimal("0"), Decimal("0")),
    # The deterministic stub used by tests and offline runs.
    "stub": Rate(Decimal("0"), Decimal("0")),
}


class UnknownModel(KeyError):
    """No published rate for this model.

    Raised rather than defaulting to zero. See the module docstring.
    """


def cost_of(model: str, usage: Usage) -> Decimal:
    """USD cost of one call.

    Args:
        model: Model identifier as the provider reports it.
        usage: Token counts from the response.

    Raises:
        UnknownModel: if the model has no published rate.
    """
    rate = RATES.get(model)
    if rate is None:
        # Providers append a dated suffix to snapshot releases, so
        # "gpt-4.1-mini-2025-04-14" has to resolve to the "gpt-4.1-mini" rate.
        #
        # The match must be the LONGEST prefix, not the first one found. Both
        # "gpt-4.1" and "gpt-4.1-mini" are prefixes of that model id, and picking
        # the shorter one bills a mini call at the full model's rate - five times
        # over, silently, on every call. That is not a hypothetical: it is what
        # this function did until a live smoke test showed the wrong number.
        candidates = [known for known in RATES if model.startswith(f"{known}-")]
        if candidates:
            rate = RATES[max(candidates, key=len)]

    if rate is None:
        raise UnknownModel(
            f"no published rate for {model!r}; add it to backstop_llm.pricing.RATES "
            f"rather than letting it bill as zero"
        )

    return rate.cost(usage)


def is_priced(model: str) -> bool:
    try:
        cost_of(model, Usage())
    except UnknownModel:
        return False
    return True


__all__ = ["MILLION", "RATES", "Rate", "UnknownModel", "cost_of", "is_priced"]
