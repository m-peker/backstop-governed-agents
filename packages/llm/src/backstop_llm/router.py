"""Which model answers which question.

The routing table is a policy document that happens to be Python. It says, for
every task class in the system, which provider and model handles it and what
happens when that provider is unavailable. Nothing else in the codebase names a
model.

Two consequences worth stating.

**Cost is steerable in one place.** Guardrail detectors and intent classification
run on the cheap tier; only the assessment, the deliberation and the customer reply
run on the strong one. Moving a task between tiers is a one-line diff whose effect
the eval cost gate measures.

**Failover is recorded, not hidden.** When the primary provider fails and a
fallback answers, the completion carries ``fell_back_from``, and that reaches the
audit entry. "Which model made this decision" has to stay answerable on the day
the primary was down.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backstop_llm.types import TaskClass

CHEAP = "cheap"
STRONG = "strong"


@dataclass(frozen=True, slots=True)
class Route:
    """One attempt: a provider and the model to ask it for."""

    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Task class to an ordered list of attempts.

    The list is the fallback chain. The first available provider wins; the rest
    are tried in order on failure.
    """

    tiers: dict[TaskClass, str]
    models: dict[tuple[str, str], str]
    provider_order: tuple[str, ...]

    def routes_for(self, task: TaskClass) -> tuple[Route, ...]:
        tier = self.tiers[task]
        routes = []
        for provider in self.provider_order:
            model = self.models.get((provider, tier))
            if model:
                routes.append(Route(provider=provider, model=model))
        return tuple(routes)


#: Which tier each task runs on. This is the cost policy.
DEFAULT_TIERS: dict[TaskClass, str] = {
    TaskClass.DETECT: CHEAP,
    TaskClass.CLASSIFY: CHEAP,
    TaskClass.ASSESS: STRONG,
    TaskClass.DELIBERATE: STRONG,
    TaskClass.ARBITRATE: STRONG,
    TaskClass.COMPOSE: STRONG,
    TaskClass.JUDGE: STRONG,
}


def default_policy() -> RoutingPolicy:
    """Build the routing policy from the environment.

    OpenAI is primary. Anthropic and a local Ollama tier follow, and a provider
    with no configured model is simply absent from every chain rather than a
    runtime failure - so a developer with one key still has a working system.
    """
    primary = os.environ.get("BACKSTOP_PRIMARY_PROVIDER", "openai").strip().lower()

    models: dict[tuple[str, str], str] = {}
    for provider, cheap_var, strong_var in (
        ("openai", "OPENAI_MODEL_CHEAP", "OPENAI_MODEL_STRONG"),
        ("anthropic", "ANTHROPIC_MODEL_CHEAP", "ANTHROPIC_MODEL_STRONG"),
    ):
        if cheap := os.environ.get(cheap_var):
            models[(provider, CHEAP)] = cheap
        if strong := os.environ.get(strong_var):
            models[(provider, STRONG)] = strong

    if ollama := os.environ.get("OLLAMA_MODEL"):
        models[("ollama", CHEAP)] = ollama
        models[("ollama", STRONG)] = ollama

    order = ["openai", "anthropic", "ollama"]
    if primary in order:
        order.remove(primary)
        order.insert(0, primary)

    return RoutingPolicy(tiers=dict(DEFAULT_TIERS), models=models, provider_order=tuple(order))


def stub_policy() -> RoutingPolicy:
    """Everything routes to the deterministic stub. The default in tests."""
    return RoutingPolicy(
        tiers=dict(DEFAULT_TIERS),
        models={("stub", CHEAP): "stub", ("stub", STRONG): "stub"},
        provider_order=("stub",),
    )


__all__ = [
    "CHEAP",
    "DEFAULT_TIERS",
    "STRONG",
    "Route",
    "RoutingPolicy",
    "default_policy",
    "stub_policy",
]
