"""Model routing, pricing and budget control."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from backstop_llm import (
    Budget,
    BudgetExhausted,
    LLMClient,
    LLMError,
    RoutingPolicy,
    StubProvider,
    TaskClass,
    Usage,
    cost_of,
    stub_policy,
)
from backstop_llm.pricing import RATES, UnknownModel
from backstop_llm.provider import ProviderResult
from backstop_llm.router import CHEAP, STRONG, default_policy


class Verdict(BaseModel):
    decision: str
    confidence: float


class Other(BaseModel):
    note: str


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_a_dated_snapshot_resolves_to_its_family() -> None:
    assert (
        cost_of("gpt-4.1-mini-2025-04-14", Usage(1_000_000, 0)) == RATES["gpt-4.1-mini"].input_usd
    )


def test_the_longest_matching_prefix_wins() -> None:
    """Regression: "gpt-4.1" is also a prefix of "gpt-4.1-mini-2025-04-14".

    Matching the first prefix found billed mini calls at the full model's rate -
    five times over, on every call, silently.
    """
    mini = cost_of("gpt-4.1-mini-2025-04-14", Usage(1_000_000, 0))
    full = cost_of("gpt-4.1-2025-04-14", Usage(1_000_000, 0))

    assert mini < full
    assert mini == Decimal("0.400000")
    assert full == Decimal("2.000000")


def test_cached_input_is_billed_at_the_discounted_rate() -> None:
    fresh = cost_of("gpt-4.1", Usage(input_tokens=1_000_000))
    cached = cost_of("gpt-4.1", Usage(input_tokens=1_000_000, cached_input_tokens=1_000_000))

    assert cached < fresh
    assert cached == RATES["gpt-4.1"].cached_input_usd


def test_an_unknown_model_raises_rather_than_costing_zero() -> None:
    """A cost meter that reports zero for the model you deployed is worse than none."""
    with pytest.raises(UnknownModel, match="no published rate"):
        cost_of("some-model-nobody-added", Usage(1000, 100))


def test_sub_cent_costs_survive_rounding() -> None:
    """One classification costs a fraction of a cent; two decimals would lose it."""
    assert cost_of("gpt-4.1-mini", Usage(88, 9)) > 0


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_cheap_tasks_and_strong_tasks_are_separated() -> None:
    policy = RoutingPolicy(
        tiers={TaskClass.CLASSIFY: CHEAP, TaskClass.ASSESS: STRONG},
        models={("openai", CHEAP): "gpt-4.1-mini", ("openai", STRONG): "gpt-4.1"},
        provider_order=("openai",),
    )

    assert policy.routes_for(TaskClass.CLASSIFY)[0].model == "gpt-4.1-mini"
    assert policy.routes_for(TaskClass.ASSESS)[0].model == "gpt-4.1"


def test_the_primary_provider_leads_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKSTOP_PRIMARY_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_MODEL_STRONG", "gpt-4.1")
    monkeypatch.setenv("ANTHROPIC_MODEL_STRONG", "claude-sonnet-5")

    routes = default_policy().routes_for(TaskClass.ASSESS)
    assert [route.provider for route in routes] == ["anthropic", "openai"]


def test_an_unconfigured_provider_is_absent_rather_than_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ANTHROPIC_MODEL_CHEAP", "ANTHROPIC_MODEL_STRONG", "OLLAMA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_MODEL_STRONG", "gpt-4.1")

    routes = default_policy().routes_for(TaskClass.ASSESS)
    assert [route.provider for route in routes] == ["openai"]


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


@pytest.fixture
def stub() -> StubProvider:
    return StubProvider()


@pytest.fixture
def client(stub: StubProvider) -> LLMClient:
    return LLMClient(providers={"stub": stub}, policy=stub_policy())


async def test_a_typed_answer_comes_back(client: LLMClient, stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="full_refund", confidence=0.9))

    completion = await client.complete(
        task=TaskClass.ASSESS, system="decide", user="a ticket", schema=Verdict
    )

    assert completion.value.decision == "full_refund"
    assert completion.provider == "stub"
    assert completion.task is TaskClass.ASSESS


async def test_the_stub_refuses_to_invent_an_answer(client: LLMClient) -> None:
    """A stub that returned a default would let a test pass on a prompt never sent.

    The refusal surfaces as an ``LLMError`` because the router treats any provider
    exception as a failed route - correct for a real provider, and the reason is
    still carried in the message.
    """
    with pytest.raises(LLMError, match="no scripted response"):
        await client.complete(task=TaskClass.ASSESS, system="decide", user="a ticket", schema=Other)


async def test_the_prompt_is_inspectable(client: LLMClient, stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="rejected", confidence=0.4))

    await client.complete(
        task=TaskClass.ASSESS, system="you decide refunds", user="ORD-0000001", schema=Verdict
    )

    assert "you decide refunds" in stub.last_prompt()
    assert "ORD-0000001" in stub.last_prompt()


async def test_every_call_lands_in_the_ledger(client: LLMClient, stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="full_refund", confidence=0.9))

    await client.complete(task=TaskClass.CLASSIFY, system="s", user="u", schema=Verdict)
    await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)

    assert set(client.ledger.breakdown()) == {"classify", "assess"}


# ---------------------------------------------------------------------------
# Failover
# ---------------------------------------------------------------------------


class BrokenProvider:
    """A provider that is configured and answers every call with a failure."""

    name = "broken"
    available = True

    async def complete(self, **kwargs: Any) -> ProviderResult[Any]:
        raise RuntimeError("provider is down")


class UnavailableProvider:
    """A provider with no credentials. The router must skip it, not call it."""

    name = "unavailable"
    available = False

    async def complete(self, **kwargs: Any) -> ProviderResult[Any]:
        raise AssertionError("an unavailable provider must never be called")


async def test_a_failed_primary_falls_through_to_the_next(stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="store_credit", confidence=0.6))
    client = LLMClient(
        providers={"broken": BrokenProvider(), "stub": stub},
        policy=RoutingPolicy(
            tiers={TaskClass.ASSESS: STRONG},
            models={("broken", STRONG): "gpt-4.1", ("stub", STRONG): "stub"},
            provider_order=("broken", "stub"),
        ),
    )

    completion = await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)

    assert completion.provider == "stub"
    # The failover is on the record, not swallowed: "which model decided this"
    # must stay answerable on the day the primary was down.
    assert completion.fell_back_from == "gpt-4.1"
    assert completion.as_audit_fields()["fell_back_from"] == "gpt-4.1"


async def test_an_unavailable_provider_is_skipped_not_called(stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="rejected", confidence=0.5))
    client = LLMClient(
        providers={"unavailable": UnavailableProvider(), "stub": stub},
        policy=RoutingPolicy(
            tiers={TaskClass.ASSESS: STRONG},
            models={("unavailable", STRONG): "x", ("stub", STRONG): "stub"},
            provider_order=("unavailable", "stub"),
        ),
    )

    completion = await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)
    assert completion.provider == "stub"


async def test_exhausting_the_chain_reports_every_failure() -> None:
    client = LLMClient(
        providers={"broken": BrokenProvider()},
        policy=RoutingPolicy(
            tiers={TaskClass.ASSESS: STRONG},
            models={("broken", STRONG): "gpt-4.1"},
            provider_order=("broken",),
        ),
    )

    with pytest.raises(LLMError, match="provider is down"):
        await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


async def test_the_ceiling_stops_further_calls(stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="full_refund", confidence=0.9))
    client = LLMClient(
        providers={"stub": stub},
        policy=RoutingPolicy(
            tiers={TaskClass.ASSESS: STRONG},
            models={("stub", STRONG): "gpt-4.1"},
            provider_order=("stub",),
        ),
        budget=Budget(Decimal("0.001")),
    )

    # The stub reports 400 in / 120 out, priced as gpt-4.1: about 0.00176 USD.
    await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)

    with pytest.raises(BudgetExhausted, match="circuit breaker"):
        await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)


async def test_no_ceiling_means_no_limit(client: LLMClient, stub: StubProvider) -> None:
    stub.script(Verdict, Verdict(decision="full_refund", confidence=0.9))

    for _ in range(50):
        await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)

    assert client.budget.remaining is None


async def test_an_exhausted_budget_refuses_rather_than_downgrading(
    stub: StubProvider,
) -> None:
    """Answering a high-stakes question with a weaker model to stay under budget
    is a cost saving that shows up later as a wrong refund.

    The ceiling is a stop-after-exceeded breaker, not a pre-flight estimate: the
    first call runs, and once spend passes the ceiling every later call is refused
    outright. It does not quietly re-route ASSESS onto the cheap tier.
    """
    stub.script(Verdict, Verdict(decision="full_refund", confidence=0.9))
    client = LLMClient(
        providers={"stub": stub},
        policy=RoutingPolicy(
            tiers={TaskClass.ASSESS: STRONG},
            models={("stub", STRONG): "gpt-4.1", ("stub", CHEAP): "gpt-4.1-mini"},
            provider_order=("stub",),
        ),
        budget=Budget(Decimal("0.0001")),
    )

    first = await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)
    assert first.model == "gpt-4.1"
    assert client.budget.exhausted

    with pytest.raises(BudgetExhausted):
        await client.complete(task=TaskClass.ASSESS, system="s", user="u", schema=Verdict)

    # One call reached the provider. There was no second, cheaper attempt.
    assert len(stub.calls) == 1
