"""The one way to call a model.

Everything above this - the graph, the guardrails, the deliberation room, the eval
judge - goes through :meth:`LLMClient.complete`. Nothing constructs a provider
client of its own.

That single entry point is what makes four properties true at once:

* every call is priced and added to a ledger;
* every call is a span with the token counts and cost on it;
* the budget ceiling is checked *before* spending, not reported after;
* a failover is recorded on the response rather than swallowed.

The budget check deserves a note. When the ceiling is reached the client raises
:class:`BudgetExhausted` rather than degrading to a cheaper model. Silently
answering a high-stakes question with a weaker model to stay under budget is the
kind of cost saving that shows up later as a wrong refund.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel

from backstop_llm.pricing import cost_of
from backstop_llm.provider import Provider
from backstop_llm.router import RoutingPolicy, stub_policy
from backstop_llm.types import (
    BudgetExhausted,
    Completion,
    CostLedger,
    LLMError,
    Message,
    Role,
    TaskClass,
)
from backstop_telemetry.otel import (
    ATTR_COST_USD,
    ATTR_MODEL,
    ATTR_TOKENS_IN,
    ATTR_TOKENS_OUT,
    tracer,
)

T = TypeVar("T", bound=BaseModel)

_TRACER = tracer(__name__)


class Budget:
    """A spend ceiling with a circuit breaker."""

    def __init__(self, ceiling_usd: Decimal | None) -> None:
        self.ceiling = ceiling_usd
        self.spent = Decimal("0")

    @property
    def remaining(self) -> Decimal | None:
        return None if self.ceiling is None else self.ceiling - self.spent

    @property
    def exhausted(self) -> bool:
        return self.ceiling is not None and self.spent >= self.ceiling

    def charge(self, amount: Decimal) -> None:
        self.spent += amount


class LLMClient:
    """Routes, calls, prices and records."""

    def __init__(
        self,
        *,
        providers: dict[str, Provider],
        policy: RoutingPolicy | None = None,
        budget: Budget | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> None:
        self._providers = providers
        self._policy = policy or stub_policy()
        self.budget = budget or Budget(None)
        self.ledger = CostLedger()
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    async def complete(
        self,
        *,
        task: TaskClass,
        system: str,
        user: str,
        schema: type[T],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Completion[T]:
        """Ask for one typed answer.

        Args:
            task: What this call is for. Decides the model tier.
            system: Instructions. Trusted content only - never customer text.
            user: The request. Untrusted content belongs here, spotlighted by the
                guardrail plane before it arrives.
            schema: The Pydantic model the answer must conform to.

        Raises:
            BudgetExhausted: the ceiling was reached before this call.
            LLMError: every route in the chain failed.
        """
        if self.budget.exhausted:
            raise BudgetExhausted(
                f"budget of {self.budget.ceiling} USD is spent; the circuit breaker has tripped"
            )

        messages = [Message(Role.SYSTEM, system), Message(Role.USER, user)]
        routes = self._policy.routes_for(task)
        if not routes:
            raise LLMError(f"no route configured for task {task.value}")

        failures: list[str] = []
        first_attempted: str | None = None

        for route in routes:
            provider = self._providers.get(route.provider)
            if provider is None or not provider.available:
                failures.append(f"{route.provider}: not available")
                continue

            if first_attempted is None:
                first_attempted = route.model

            started = time.perf_counter()
            try:
                result = await provider.complete(
                    model=route.model,
                    messages=messages,
                    schema=schema,
                    temperature=temperature if temperature is not None else self._temperature,
                    max_output_tokens=max_output_tokens or self._max_output_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - boundary: try the next route
                failures.append(f"{route.provider}/{route.model}: {type(exc).__name__}: {exc}")
                continue

            latency_ms = (time.perf_counter() - started) * 1000
            cost = cost_of(result.model, result.usage)

            self.budget.charge(cost)
            self.ledger.record(task.value, cost)

            completion = Completion(
                value=result.value,
                text=result.text,
                model=result.model,
                provider=provider.name,
                task=task,
                usage=result.usage,
                cost_usd=cost,
                latency_ms=latency_ms,
                fell_back_from=first_attempted if result.model != first_attempted else None,
            )
            self._record_span(completion)
            return completion

        raise LLMError(f"every route for {task.value} failed: " + "; ".join(failures))

    def _record_span(self, completion: Completion[BaseModel]) -> None:
        with _TRACER.start_as_current_span(f"llm.{completion.task.value}") as span:
            span.set_attribute(ATTR_MODEL, completion.model)
            span.set_attribute(ATTR_TOKENS_IN, completion.usage.input_tokens)
            span.set_attribute(ATTR_TOKENS_OUT, completion.usage.output_tokens)
            span.set_attribute(ATTR_COST_USD, float(completion.cost_usd))
            if completion.fell_back_from:
                span.set_attribute("backstop.fell_back_from", completion.fell_back_from)


def build_client(
    *,
    budget_usd: Decimal | None = None,
    prefer_stub: bool = False,
) -> LLMClient:
    """Assemble a client from the environment.

    Falls back to the stub when no provider key is configured, so importing this
    never explodes on a machine without credentials. Whether that fallback
    happened is visible: the completion's ``provider`` will read ``stub``.
    """
    from backstop_llm.providers.openai_provider import OpenAIProvider
    from backstop_llm.providers.stub import StubProvider
    from backstop_llm.router import default_policy

    if prefer_stub:
        return LLMClient(providers={"stub": StubProvider()}, policy=stub_policy())

    openai = OpenAIProvider()
    if not openai.available:
        return LLMClient(
            providers={"stub": StubProvider()},
            policy=stub_policy(),
            budget=Budget(budget_usd),
        )

    return LLMClient(
        providers={"openai": openai},
        policy=default_policy(),
        budget=Budget(budget_usd),
    )


__all__ = ["Budget", "LLMClient", "build_client"]
