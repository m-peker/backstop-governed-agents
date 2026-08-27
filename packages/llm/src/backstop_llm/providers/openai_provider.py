"""OpenAI provider.

Uses the SDK's ``chat.completions.parse``, which sends the Pydantic model as a
strict JSON schema and validates the response against it. That is meaningfully
stronger than asking for JSON in the prompt: the model is constrained at decode
time, so a malformed decision is not something the guardrail plane has to catch
later - it cannot be produced.

The provider does not retry. Retry policy belongs to the router, which knows about
fallbacks and budgets; a provider that retried on its own would multiply the
router's attempts by its own and quietly spend several times the intended amount.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

from pydantic import BaseModel

from backstop_llm.provider import ProviderResult
from backstop_llm.types import LLMError, Message, Usage

if TYPE_CHECKING:
    from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    """Chat completions with schema-constrained output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._client: AsyncOpenAI | None = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _ensure_client(self) -> AsyncOpenAI:
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key, base_url=self._base_url, timeout=self._timeout
            )
        return self._client

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        schema: type[T],
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderResult[T]:
        if not self.available:
            raise LLMError("OPENAI_API_KEY is not set")

        client = self._ensure_client()

        completion = await client.chat.completions.parse(
            model=model,
            messages=cast(Any, [message.as_dict() for message in messages]),
            response_format=schema,
            temperature=temperature,
            max_completion_tokens=max_output_tokens,
        )

        choice = completion.choices[0]
        parsed = choice.message.parsed

        if parsed is None:
            # Happens on a refusal or a length cut-off. Both mean the decision was
            # never produced, and inventing one here would be the worst option.
            refusal = getattr(choice.message, "refusal", None)
            reason = refusal or f"finish_reason={choice.finish_reason}"
            raise LLMError(f"{model} returned no parsed value ({reason})")

        return ProviderResult(
            value=parsed,
            text=choice.message.content or "",
            model=completion.model,
            usage=_usage_of(completion.usage),
        )


def _usage_of(raw: Any) -> Usage:
    if raw is None:
        return Usage()

    details = getattr(raw, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0

    return Usage(
        input_tokens=getattr(raw, "prompt_tokens", 0) or 0,
        output_tokens=getattr(raw, "completion_tokens", 0) or 0,
        cached_input_tokens=cached,
    )


__all__ = ["OpenAIProvider"]
