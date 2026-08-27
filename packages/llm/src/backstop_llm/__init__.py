"""Model access.

One client, one routing table, one cost ledger. Nothing above this package names
a model or constructs a provider.
"""

from backstop_llm.client import Budget, LLMClient, build_client
from backstop_llm.pricing import RATES, UnknownModel, cost_of
from backstop_llm.provider import Provider, ProviderResult
from backstop_llm.providers.stub import NoScriptedResponse, StubProvider
from backstop_llm.router import RoutingPolicy, default_policy, stub_policy
from backstop_llm.types import (
    BudgetExhausted,
    Completion,
    CostLedger,
    LLMError,
    Message,
    Role,
    TaskClass,
    Usage,
)

__all__ = [
    "RATES",
    "Budget",
    "BudgetExhausted",
    "Completion",
    "CostLedger",
    "LLMClient",
    "LLMError",
    "Message",
    "NoScriptedResponse",
    "Provider",
    "ProviderResult",
    "Role",
    "RoutingPolicy",
    "StubProvider",
    "TaskClass",
    "UnknownModel",
    "Usage",
    "build_client",
    "cost_of",
    "default_policy",
    "stub_policy",
]
