"""The deliberation room.

Three agents argue and a fourth decides. It convenes only when the resolution
graph reaches a case the policy does not settle - a genuine conflict between
clauses, or a term the policy uses and never defines.

The shape of it:

* **PolicyAnalyst** argues from the clauses as written, and may not invent
  exceptions.
* **CustomerAdvocate** argues for the customer, from their history and the cost of
  getting it wrong in that direction.
* **FraudInvestigator** argues the adversarial case from the evidence.
* **Arbiter** does not participate. It reads the transcript and produces a
  structured verdict, including the strongest argument against its own conclusion.

Four constraints hold the room together, and each exists because of a specific
failure it prevents:

**Read-only, and no tools at all.** Every participant is a read-only principal,
and the model client refuses tool calls outright. An unbounded conversation with
tool access is an unbounded number of tool calls.

**A hard round cap.** Agents that agree stop; agents that do not would otherwise
continue indefinitely. The cap is on messages, not on agreement.

**A token budget for the room.** Charged to the same ledger as everything else, so
a debate that runs long shows up in the per-ticket cost rather than hiding in it.

**The verdict is data.** The room returns a recommendation to the graph. It never
executes, never terminates a ticket, and never decides that a human is unnecessary.
That last point matters: the room is convened *because* the case is hard, so its
own confidence is the least reliable thing about it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import StructuredMessage
from autogen_agentchat.teams import RoundRobinGroupChat

from backstop_deliberation.bridge import BackstopChatCompletionClient
from backstop_graph.schemas import DeliberationTurn, DeliberationVerdict
from backstop_llm import LLMClient, TaskClass
from backstop_toolgateway.principal import (
    DELIBERATION_ARBITER,
    DELIBERATION_CUSTOMER_ADVOCATE,
    DELIBERATION_FRAUD_INVESTIGATOR,
    DELIBERATION_POLICY_ANALYST,
    Principal,
)

#: Messages, not rounds. Three speakers plus the arbiter's read means a cap of 9
#: gives every participant two turns and a closing word.
DEFAULT_MAX_MESSAGES = 9


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    principal: Principal
    mandate: str


ROLES: tuple[Role, ...] = (
    Role(
        name="PolicyAnalyst",
        principal=DELIBERATION_POLICY_ANALYST,
        mandate=(
            "Argue strictly from the policy clauses as written. Quote the clause "
            "identifiers you rely on. You may point out that two clauses conflict, "
            "and you may say a term is undefined. You may not invent an exception, "
            "and you may not read a clause more generously than it is written "
            "because the outcome would be kinder."
        ),
    ),
    Role(
        name="CustomerAdvocate",
        principal=DELIBERATION_CUSTOMER_ADVOCATE,
        mandate=(
            "Argue for the customer. Weigh their history, what this decision costs "
            "them, and what getting it wrong in this direction costs the business "
            "in a relationship it has already paid to acquire. Do not claim facts "
            "the record does not support, and do not argue that a clear rule should "
            "be ignored because the customer is unhappy."
        ),
    ),
    Role(
        name="FraudInvestigator",
        principal=DELIBERATION_FRAUD_INVESTIGATOR,
        mandate=(
            "Argue the adversarial case from the evidence: return rate, claim "
            "frequency, delivery evidence, accounts sharing an address, account "
            "age. Say plainly when the evidence does not support suspicion - a "
            "case with no indicators is a case you should say is clean. You are "
            "arguing for scrutiny, not for refusal, and you have no authority to "
            "decline anything."
        ),
    ),
)

ARBITER = Role(
    name="Arbiter",
    principal=DELIBERATION_ARBITER,
    mandate="Weigh the arguments and conclude. You did not participate.",
)


@dataclass(slots=True)
class DeliberationRecord:
    """What happened in the room. Goes into the graph state and the dossier."""

    verdict: DeliberationVerdict
    transcript: list[dict[str, str]] = field(default_factory=list)
    rounds: int = 0
    cost_usd: str = "0"
    hit_round_cap: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.verdict.resolution.value,
            "amount_eur": self.verdict.amount_eur,
            "cited_clauses": list(self.verdict.cited_clauses),
            "rationale": self.verdict.rationale,
            "dissent": self.verdict.dissent,
            "confidence": self.verdict.confidence,
            "rounds": self.rounds,
            "hit_round_cap": self.hit_round_cap,
            "cost_usd": self.cost_usd,
            "transcript": self.transcript,
        }


class DeliberationRoom:
    """Convene the room for one case."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        preamble: str = "",
    ) -> None:
        self._llm = llm
        self._max_messages = max_messages
        self._preamble = preamble

    def _agent(self, role: Role, brief: str) -> AssistantAgent:
        client = BackstopChatCompletionClient(self._llm, task=TaskClass.DELIBERATE)
        return AssistantAgent(
            name=role.name,
            model_client=client,
            output_content_type=DeliberationTurn,
            system_message=(
                f"{self._preamble}\n\n"
                f"You are the {role.name} in a review of a difficult customer case.\n\n"
                f"{role.mandate}\n\n"
                f"You are arguing one side on purpose. Others argue the rest and an "
                f"arbiter weighs all of it. Make the strongest honest case from the "
                f"facts and clauses you were given. Keep it to one argument, well "
                f"made, citing the clauses it rests on.\n\n"
                f"{brief}"
            ),
        )

    async def deliberate(self, *, brief: str) -> DeliberationRecord:
        """Run the room over a prepared brief.

        Args:
            brief: Facts, retrieved clauses and the question, already assembled and
                spotlighted by the caller. The room never gathers anything itself.
        """
        spent_before = self._llm.ledger.total

        team = RoundRobinGroupChat(
            participants=[self._agent(role, brief) for role in ROLES],
            termination_condition=MaxMessageTermination(self._max_messages),
            # Every agent emits a typed DeliberationTurn rather than prose, so the
            # runtime has to be told that message type exists before it can route
            # it. This is the price of never parsing a model's free text.
            custom_message_types=[StructuredMessage[DeliberationTurn]],
        )

        result = await team.run(task="Give your argument on this case.")

        transcript: list[dict[str, str]] = []
        for message in result.messages:
            source = getattr(message, "source", "unknown")
            content = getattr(message, "content", "")
            transcript.append({"speaker": source, "argument": _readable(content)})

        verdict = await self._arbitrate(brief=brief, transcript=transcript)

        return DeliberationRecord(
            verdict=verdict,
            transcript=transcript,
            rounds=len(transcript),
            cost_usd=str(self._llm.ledger.total - spent_before),
            hit_round_cap=len(transcript) >= self._max_messages,
        )

    async def _arbitrate(
        self, *, brief: str, transcript: list[dict[str, str]]
    ) -> DeliberationVerdict:
        """The arbiter reads and concludes.

        Run through the Backstop client directly rather than as a fourth AutoGen
        participant. The arbiter is not part of the conversation - it is the thing
        that reads the conversation - and modelling it as a participant would let
        it be argued with.
        """
        argument_text = "\n\n".join(
            f"[{turn['speaker']}] {turn['argument']}" for turn in transcript
        )

        completion = await self._llm.complete(
            task=TaskClass.ARBITRATE,
            system=(
                f"{self._preamble}\n\n"
                "You are the arbiter. You did not participate and you have no "
                "position to defend. Weigh what was argued against the facts and "
                "the clauses.\n\n"
                "Record the strongest argument against your own conclusion in the "
                "dissent field. A conclusion that suppressed its counter-argument "
                "cannot be reviewed, which makes it worth less than one that states "
                "it.\n\n"
                "If the arguments show the policy genuinely does not settle this, "
                "choose escalate. That is a correct verdict, not a failure to reach one."
            ),
            user=f"{brief}\n\nThe arguments made:\n\n{argument_text}",
            schema=DeliberationVerdict,
        )
        return completion.value


def _readable(content: Any) -> str:
    """Turns come back as structured JSON. Render the argument for a human."""
    if isinstance(content, DeliberationTurn):
        return content.argument
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
        if isinstance(parsed, dict) and "argument" in parsed:
            return str(parsed["argument"])
        return content
    return str(content)


def amount_of(verdict: DeliberationVerdict) -> Decimal | None:
    from decimal import InvalidOperation

    if verdict.amount_eur is None:
        return None
    try:
        return Decimal(verdict.amount_eur)
    except InvalidOperation:
        return None


__all__ = [
    "ARBITER",
    "DEFAULT_MAX_MESSAGES",
    "ROLES",
    "DeliberationRecord",
    "DeliberationRoom",
    "Role",
    "amount_of",
]
