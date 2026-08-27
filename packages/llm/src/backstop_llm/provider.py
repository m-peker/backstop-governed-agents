"""The provider contract.

One method. A provider takes messages and a Pydantic schema, and returns an
instance of that schema plus the tokens it burned.

**Structured output is the only mode.** There is no `complete_text`. Every call in
this system produces a typed object, because the alternative - parsing prose for a
decision - is how a refund system ends up refunding the wrong amount because a
model wrote "no refund is warranted, unless" and a regex found the wrong clause.
The reply text a customer eventually reads is itself a *field* on a validated
object, not the raw completion.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel

from backstop_llm.types import Message, Usage

T = TypeVar("T", bound=BaseModel)


class ProviderResult[T: BaseModel](BaseModel):
    """What a provider hands back before cost is applied."""

    model_config = {"arbitrary_types_allowed": True}

    value: T
    text: str
    model: str
    usage: Usage


class Provider(Protocol):
    """A model backend."""

    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool:
        """Whether this provider is configured well enough to be tried.

        The router skips unavailable providers instead of failing, so a developer
        with only one key set still gets a working system.
        """
        ...

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        schema: type[T],
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderResult[T]: ...


__all__ = ["Provider", "ProviderResult"]
