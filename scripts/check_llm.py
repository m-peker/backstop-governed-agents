"""Verify the model wiring with one small live call.

Deliberately separate from the test suite. The tests run against the deterministic
stub and must stay free, fast and offline; this is the one place that proves the
real provider is reachable, the schema constraint works, and the cost meter
produces a number that matches the invoice.

Run it after changing a key, a model or the routing table::

    uv run python scripts/check_llm.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class Ping(BaseModel):
    """A schema small enough that the call costs a fraction of a cent."""

    answer: str = Field(description="The single word 'pong'")
    confidence: float = Field(ge=0, le=1)


async def main() -> int:
    load_dotenv(REPOSITORY_ROOT / ".env")

    from backstop_llm import LLMClient, TaskClass, default_policy
    from backstop_llm.client import Budget
    from backstop_llm.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider()
    if not provider.available:
        print("OPENAI_API_KEY is not set - nothing to check")
        return 1

    policy = default_policy()
    print(f"primary provider        {os.environ.get('BACKSTOP_PRIMARY_PROVIDER', 'openai')}")
    for task in (TaskClass.CLASSIFY, TaskClass.ASSESS):
        routes = policy.routes_for(task)
        chain = " -> ".join(f"{route.provider}/{route.model}" for route in routes)
        print(f"{task.value:<24}{chain}")

    client = LLMClient(
        providers={"openai": provider},
        policy=policy,
        budget=Budget(Decimal("0.05")),
    )

    print("\ncalling...")
    try:
        completion = await client.complete(
            task=TaskClass.CLASSIFY,
            system="You reply with the single word pong.",
            user="ping",
            schema=Ping,
            max_output_tokens=64,
        )
    except Exception as exc:  # noqa: BLE001 - this script exists to report failures
        print(f"\nFAILED  {type(exc).__name__}: {exc}")
        return 1

    print(f"\nmodel                   {completion.model}")
    print(f"answer                  {completion.value.answer!r}")
    print(f"schema honoured         {isinstance(completion.value, Ping)}")
    print(
        f"tokens                  {completion.usage.input_tokens} in, "
        f"{completion.usage.output_tokens} out"
    )
    print(f"cost                    USD {completion.cost_usd}")
    print(f"latency                 {completion.latency_ms:.0f} ms")
    print(f"budget remaining        USD {client.budget.remaining}")

    if completion.cost_usd <= 0:
        print("\nWARNING: the call was priced at zero - check backstop_llm.pricing.RATES")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
