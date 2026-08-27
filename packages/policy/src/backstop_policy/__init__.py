"""Policy-as-code.

What an agent may do, expressed as versioned, unit-tested rules that live outside
the application code and outside any prompt. The model proposes; this decides.
"""

from backstop_policy.context import (
    CustomerTier,
    EvidenceStrength,
    Intent,
    PolicyContext,
    Resolution,
)
from backstop_policy.engine import PolicyDecision, PolicyEngine
from backstop_policy.rules import ALL_RULES, Effect, Rule, Ruling

__all__ = [
    "ALL_RULES",
    "CustomerTier",
    "Effect",
    "EvidenceStrength",
    "Intent",
    "PolicyContext",
    "PolicyDecision",
    "PolicyEngine",
    "Resolution",
    "Rule",
    "Ruling",
]
