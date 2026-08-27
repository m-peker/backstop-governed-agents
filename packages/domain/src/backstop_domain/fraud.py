"""Seeded abuse patterns and their ground truth.

The generator plants a small number of return-abuse patterns in the synthetic
dataset. Each one is *detectable from the data the tools expose* - no pattern
relies on information an agent could not reach through the MCP servers. That
constraint is what makes them usable as evaluation labels: if the fraud
investigator misses one, the miss is the agent's, not the data's.

:class:`FraudAnnotation` is ground truth. It is written to the dataset for the
eval harness and is **never** exposed through an MCP tool. An agent that could
read the labels would score perfectly and tell us nothing.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FraudPattern(StrEnum):
    """Return-abuse patterns planted in the dataset."""

    SERIAL_REFUNDER = "serial_refunder"
    """An implausible share of this customer's orders end in a refund."""

    WARDROBING = "wardrobing"
    """High-value apparel repeatedly returned just inside the return window."""

    ADDRESS_REUSE = "address_reuse"
    """Several accounts share one delivery address, each filing claims."""

    DELIVERY_CLAIM_ABUSE = "delivery_claim_abuse"
    """Repeated "never arrived" claims against shipments with signature and photo."""

    HIGH_VALUE_NEWCOMER = "high_value_newcomer"
    """A days-old account places a top-decile order and immediately claims damage."""


#: What an investigator would have to notice to catch each pattern. Used in the
#: eval rubric so that partial credit is awarded for the right reasoning rather
#: than a lucky verdict.
DETECTION_SIGNALS: dict[FraudPattern, tuple[str, ...]] = {
    FraudPattern.SERIAL_REFUNDER: (
        "return rate across the customer's order history",
        "number of prior refunds relative to tenure",
    ),
    FraudPattern.WARDROBING: (
        "returns clustered in the final days of the return window",
        "high unit price concentrated in one category",
        "reason codes that avoid fault (changed mind, size)",
    ),
    FraudPattern.ADDRESS_REUSE: (
        "delivery address shared by several customer accounts",
        "claims filed from each of those accounts",
    ),
    FraudPattern.DELIVERY_CLAIM_ABUSE: (
        "carrier recorded a signature and a delivery photo",
        "prior never-arrived claims by the same customer",
    ),
    FraudPattern.HIGH_VALUE_NEWCOMER: (
        "account age at the time of the order",
        "order value in the top decile",
        "damage claim filed within days of delivery",
    ),
}


class FraudAnnotation(BaseModel):
    """Ground truth for one planted pattern.

    Not exposed by any tool. Lives in the dataset purely so the eval harness can
    score detection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: FraudPattern
    customer_ids: tuple[str, ...] = Field(min_length=1)
    order_ids: tuple[str, ...] = ()
    note: str = ""

    @property
    def signals(self) -> tuple[str, ...]:
        return DETECTION_SIGNALS[self.pattern]


__all__ = ["DETECTION_SIGNALS", "FraudAnnotation", "FraudPattern"]
