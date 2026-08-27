"""The resolution graph.

Control flow is code, in one place, reviewable in a diff. That is the argument for
a state machine over an agent loop: you can read this file and know every path a
ticket can take, and so can the person reviewing the pull request that changes one.

    guardrail_in ─blocked─────────────────────────────────────────────► close
         │
      classify ─► gather_facts ─► policy_retrieval ─► assess ─► policy_gate
                                                                     │
                    ┌──permit─────────────────────────────────────┬──┴──┬──deny──┐
                    │                                             │     │        │
                 execute                     the policy contradicts     │        │
                    │                              itself │            │        │
                    │                                deliberate        │        │
                    │                                     │            │        │
                    │                                     └─► human_approval    │
                    │                                            │      │       │
                    └──────────────► compose_reply ◄─────────────┘  declined ◄──┘
                                          │            approved
                                     guardrail_out
                                          │
                                        close

The routing rules, stated once so the conditional functions below are read against
them:

* An input guardrail block ends the ticket without a model ever seeing it.
* The policy engine's ``DENY`` still produces a reply - a customer who is refused
  is owed an explanation, so the graph composes one.
* ``REQUIRE_HUMAN`` from any source pauses at ``human_approval``. "Any source"
  means the rules, a low-confidence assessment, or the model saying so itself.
* A declined approval skips execution and goes straight to composing the refusal.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from backstop_graph.nodes import make_nodes
from backstop_graph.runtime import Runtime
from backstop_graph.state import ResolutionState, Status


def _after_guardrail_in(state: ResolutionState) -> Literal["classify", "close"]:
    return "close" if state.get("status") == Status.BLOCKED.value else "classify"


def _after_policy_gate(
    state: ResolutionState,
) -> Literal["execute", "deliberate", "human_approval", "compose_reply"]:
    decision = state.get("policy_decision", {})
    effect = decision.get("effect")

    if effect == "deny":
        # A refusal is still an answer. The customer is owed the reason.
        return "compose_reply"

    needs_person = (
        effect == "require_human"
        or decision.get("low_confidence")
        or decision.get("model_asked_for_human")
    )

    if not needs_person:
        return "execute"

    # A person is required either way. The question is whether the case is worth
    # arguing first. A clear rule - an amount over the ceiling - has nothing to
    # argue about; someone simply has to decide. A contradiction in the policy has
    # a real case on each side, and the reviewer should not have to construct both
    # of them alone.
    if decision.get("needs_deliberation"):
        return "deliberate"

    return "human_approval"


def _after_human_approval(state: ResolutionState) -> Literal["execute", "compose_reply"]:
    approval = state.get("approval") or {}
    return "execute" if approval.get("approved") else "compose_reply"


def build_graph(runtime: Runtime) -> StateGraph[ResolutionState, Any, Any, Any]:
    """Wire the nodes. Returns the uncompiled graph so a caller chooses the
    checkpointer - which is the only thing that differs between a test, a lab and
    a deployment."""
    nodes = make_nodes(runtime)
    graph: StateGraph[ResolutionState, Any, Any, Any] = StateGraph(ResolutionState)

    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, "guardrail_in")
    graph.add_conditional_edges("guardrail_in", _after_guardrail_in)

    graph.add_edge("classify", "gather_facts")
    graph.add_edge("gather_facts", "policy_retrieval")
    graph.add_edge("policy_retrieval", "assess")
    graph.add_edge("assess", "policy_gate")

    graph.add_conditional_edges("policy_gate", _after_policy_gate)

    # The room informs the decision; it never makes it. There is no edge from
    # deliberate to execute, and that absence is the guarantee - not a rule in a
    # prompt, not a check inside the room, just an edge that does not exist.
    graph.add_edge("deliberate", "human_approval")

    graph.add_conditional_edges("human_approval", _after_human_approval)

    graph.add_edge("execute", "compose_reply")
    graph.add_edge("compose_reply", "guardrail_out")
    graph.add_edge("guardrail_out", "close")
    graph.add_edge("close", END)

    return graph


def compile_graph(runtime: Runtime, *, checkpointer: Any = None) -> Any:
    """Compile with a checkpointer.

    Without one the graph still runs but cannot pause: ``interrupt()`` needs
    somewhere to persist the state it is suspending. Tests that exercise the
    approval path pass ``InMemorySaver``; the labs and the API pass the SQLite
    saver; deployment passes Postgres.
    """
    return build_graph(runtime).compile(checkpointer=checkpointer)


__all__ = ["build_graph", "compile_graph"]
