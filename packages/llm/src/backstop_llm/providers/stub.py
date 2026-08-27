"""A deterministic provider.

Every test in this repository runs against this. That is a deliberate position, not
a convenience: a test suite that calls a live model is slow, costs money, and is
non-deterministic, which means it either flakes or gets weakened until it stops
catching anything.

What the stub does *not* do is pretend to be a model. It answers from a scripted
table keyed by task class, and it fails loudly when asked something it has no
answer for. A stub that quietly returned a default would let a test pass while the
prompt it was meant to exercise was never sent.

Live models are exercised in two places instead: the eval harness, and tests
marked ``live`` that only run when a key is present.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from backstop_llm.provider import ProviderResult
from backstop_llm.types import LLMError, Message, Usage

T = TypeVar("T", bound=BaseModel)

#: Builds a response from the messages it was given. Receiving the messages is the
#: point: a script can assert that the prompt actually contained what it should.
Responder = Callable[[Sequence[Message]], BaseModel]


class NoScriptedResponse(LLMError):
    """The stub was asked something it has no scripted answer for."""


class StubProvider:
    """Scripted responses, keyed by the schema being requested."""

    def __init__(self, *, tokens_per_call: tuple[int, int] = (400, 120)) -> None:
        self._responders: dict[str, Responder] = {}
        self._input_tokens, self._output_tokens = tokens_per_call
        self.calls: list[tuple[str, list[Message]]] = []

    @property
    def name(self) -> str:
        return "stub"

    @property
    def available(self) -> bool:
        return True

    def script(self, schema: type[BaseModel], responder: Responder | BaseModel) -> StubProvider:
        """Register what to return when ``schema`` is requested.

        Pass a value for a fixed answer, or a callable to vary by prompt.
        Returns self, so scripts read as a chain.
        """
        if isinstance(responder, BaseModel):
            fixed = responder
            self._responders[schema.__name__] = lambda _messages: fixed
        else:
            self._responders[schema.__name__] = responder
        return self

    def last_prompt(self) -> str:
        """The full text of the most recent call. For asserting on prompts."""
        if not self.calls:
            raise AssertionError("the stub has not been called")
        return "\n".join(message.content for message in self.calls[-1][1])

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        schema: type[T],
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderResult[T]:
        self.calls.append((schema.__name__, list(messages)))

        responder = self._responders.get(schema.__name__)
        if responder is None:
            raise NoScriptedResponse(
                f"no scripted response for {schema.__name__}; "
                f"call stub.script({schema.__name__}, ...) in the test"
            )

        value: Any = responder(messages)
        if not isinstance(value, schema):
            raise NoScriptedResponse(
                f"scripted response for {schema.__name__} returned {type(value).__name__} instead"
            )

        return ProviderResult(
            value=value,
            text=value.model_dump_json(),
            # Echo back the model that was asked for, the way a real provider
            # does. Returning a fixed "stub" here would price every call at zero
            # and quietly disable every budget test written against it.
            model=model,
            usage=Usage(input_tokens=self._input_tokens, output_tokens=self._output_tokens),
        )


__all__ = ["NoScriptedResponse", "Responder", "StubProvider"]
