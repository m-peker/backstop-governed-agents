"""Running AutoGen through the Backstop model client.

AutoGen ships its own model clients that talk to a provider directly. Using one
would mean the deliberation room's spending never reached the cost ledger, never
counted against the budget ceiling, never produced a span, and never appeared in
the "which model decided this" record. The room would be the one part of the
system nobody could account for - which is precisely the part where an unbounded
number of turns can burn an unbounded number of tokens.

So AutoGen gets a client that implements its contract and routes every call
through :class:`~backstop_llm.LLMClient`. AutoGen orchestrates; Backstop meters.

One consequence worth stating: this client advertises no function calling. That is
not a limitation being worked around, it is the design. Debating agents reason
about facts that were already gathered and handed to them. Letting the room call
tools would put an unbounded number of tool calls behind an unbounded number of
conversational turns, and the read-only scopes would then be the only thing
standing between a long argument and a very large bill.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any

from autogen_core import CancellationToken
from autogen_core.models import (
    AssistantMessage,
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    ModelFamily,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
)
from autogen_core.tools import Tool, ToolSchema
from pydantic import BaseModel

from backstop_llm import LLMClient, TaskClass


class FreeText(BaseModel):
    """Schema for a turn that has no structure of its own.

    The Backstop client only produces validated objects, so even an unstructured
    contribution to the debate comes back as a typed field. This costs nothing and
    means there is no code path anywhere that parses a model's prose.
    """

    text: str


def _render(messages: Sequence[LLMMessage]) -> tuple[str, str]:
    """Flatten AutoGen's message list into the system/user pair Backstop uses.

    AutoGen conversations interleave many turns; Backstop takes one system prompt and
    one user prompt. The transcript is rendered into the user half with speaker
    labels, which is what a model reads anyway, and keeps the untrusted-content
    rule intact: nothing from a conversation ever reaches the system half.
    """
    system_parts: list[str] = []
    transcript: list[str] = []

    for message in messages:
        content = message.content
        text = content if isinstance(content, str) else str(content)

        if isinstance(message, SystemMessage):
            system_parts.append(text)
        elif isinstance(message, UserMessage | AssistantMessage):
            transcript.append(f"[{message.source}] {text}")
        else:
            transcript.append(text)

    return "\n\n".join(system_parts), "\n\n".join(transcript)


class BackstopChatCompletionClient(ChatCompletionClient):
    """AutoGen's model client, backed by the Backstop client."""

    def __init__(self, llm: LLMClient, *, task: TaskClass = TaskClass.DELIBERATE) -> None:
        self._llm = llm
        self._task = task
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._last = RequestUsage(prompt_tokens=0, completion_tokens=0)

    # -- the contract -----------------------------------------------------

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            vision=False,
            # Deliberately false. See the module docstring: the room argues about
            # facts it was given, it does not go and fetch more.
            function_calling=False,
            json_output=True,
            family=ModelFamily.UNKNOWN,
            structured_output=True,
            multiple_system_messages=True,
        )

    @property
    def capabilities(self) -> ModelInfo:  # pragma: no cover - deprecated alias
        return self.model_info

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[BaseModel] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> CreateResult:
        if tools:
            raise NotImplementedError(
                "the deliberation room is read-only and does not call tools; "
                "facts are gathered before the room convenes"
            )

        schema: type[BaseModel] = (
            json_output
            if isinstance(json_output, type) and issubclass(json_output, BaseModel)
            else FreeText
        )
        system, user = _render(messages)

        completion = await self._llm.complete(
            task=self._task,
            system=system or "You are a participant in a structured review.",
            user=user,
            schema=schema,
        )

        self._prompt_tokens += completion.usage.input_tokens
        self._completion_tokens += completion.usage.output_tokens
        self._last = RequestUsage(
            prompt_tokens=completion.usage.input_tokens,
            completion_tokens=completion.usage.output_tokens,
        )

        value = completion.value
        content = value.text if isinstance(value, FreeText) else value.model_dump_json()

        return CreateResult(
            finish_reason="stop",
            content=content,
            usage=self._last,
            cached=False,
        )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[BaseModel] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncGenerator[str | CreateResult, None]:
        """Not a real stream.

        Backstop calls are structured-output calls, which are validated whole. There
        is nothing meaningful to emit before the object is complete, so this
        yields the finished result once rather than pretending to stream.
        """
        result = await self.create(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )
        yield result

    async def close(self) -> None:
        return None

    def actual_usage(self) -> RequestUsage:
        return self._last

    def total_usage(self) -> RequestUsage:
        return RequestUsage(
            prompt_tokens=self._prompt_tokens, completion_tokens=self._completion_tokens
        )

    def count_tokens(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = (),
        tool_choice: Any = "auto",
    ) -> int:
        """A rough estimate, and honest about it.

        AutoGen uses this to decide when a context is getting full. Four characters
        per token is close enough for that decision and does not require shipping a
        tokenizer for every model the router might reach. The *billed* figure is
        never estimated: it comes from the provider's own usage report.
        """
        system, user = _render(messages)
        return (len(system) + len(user)) // 4

    def remaining_tokens(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = (),
        tool_choice: Any = "auto",
    ) -> int:
        return max(0, 120_000 - self.count_tokens(messages, tools=tools))


__all__ = ["BackstopChatCompletionClient", "FreeText"]
