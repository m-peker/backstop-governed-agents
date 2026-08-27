# When is a multi-agent debate worth its cost?

Multi-agent systems are usually sold on the strength of the metaphor. Give the
model several roles, let them argue, and the disagreement surfaces things a single
pass would miss.

Sometimes that is true. It is expensive enough that "sometimes" needs a definition.

## The cost is not subtle

A single assessment call on this system's strong tier costs roughly $0.004. A
deliberation with three roles and a bounded transcript costs six to eight times
that, takes several times as long, and — the part people forget — is
non-deterministic in a way a single structured call is not. Run the same ticket
through the room ten times and you will not get ten identical verdicts.

For a system that resolves customer complaints, most of which are not close calls,
convening a debate on every ticket would multiply the bill and the latency to buy
disagreement on cases that were never in doubt.

So the question is not "is debate useful". It is: **which cases is it useful for,
and who decides?**

## The answer this system settled on

Not the graph, and not a confidence threshold. The *policy engine* decides.

Every rule that fires produces a `Ruling`, and a ruling carries a flag:

```python
#: Whether this ruling exists because the policy contradicts itself, as
#: opposed to because a clear rule applies.
ambiguous: bool = False
```

That distinction is the whole routing decision.

**A clear rule that requires a human** — an amount over the approval ceiling, a
customer who asked for a person, a refund larger than the order — goes straight to
the approval queue. There is nothing to argue about. Someone simply has to decide,
and spending eight model calls staging a debate before they do would produce a
transcript nobody needs.

**A ruling that exists because two clauses disagree** goes to the room first.

The seven planted contradictions in
[`seed-data/policies/ambiguities.yaml`](../../seed-data/policies/ambiguities.yaml)
are the cases this is built for. Take AMB-01: RP-4.2 requires damage to be reported
within 48 hours and attaches no consequence to missing it. RP-4.1 grants the remedy
unconditionally with no time limit of its own. A customer reports damage on day
twelve.

There is a real argument on each side. Read one way RP-4.2 is a condition of the
remedy; read the other it is our internal deadline for recovering from the carrier,
which is our problem rather than the customer's. The policy does not say. A reviewer
handed that case cold has to construct both readings themselves before they can
choose between them — and that is exactly the work the room can do.

## What the room is not allowed to do

Three constraints, and each exists because of a specific way this goes wrong.

**It cannot execute.** There is no edge from `deliberate` to `execute` in the
graph. Not a rule in a prompt, not a check inside the room — an edge that does not
exist. The room recommends and a person decides.

**It cannot call tools.** The model client the room runs on advertises
`function_calling: false` and refuses tool calls outright. An unbounded conversation
with tool access is an unbounded number of tool calls, and the read-only scopes
would then be the only thing between a long argument and a very large bill.

**It cannot spend unaccounted.** AutoGen ships its own model clients that talk to a
provider directly. Using one would mean the room's spending never reached the cost
ledger, never counted against the budget ceiling, and never appeared in the "which
model decided this" record — in the one part of the system where the number of
calls is not fixed in advance. So AutoGen gets a client that implements its contract
and routes every call through the same metered path as everything else. AutoGen
orchestrates; the platform meters.

## The part worth arguing about

The room's own confidence is the least reliable thing it produces.

It is convened *because* the case is hard. A verdict that comes back at 0.9
confidence on a question the policy genuinely does not settle is not evidence that
the question was easy; it is evidence that the model did not notice how hard it
was. So the verdict never sets the outcome. It is attached to the approval request
as a prepared case, and the field that earns its place is the one nobody asks for:

```python
dissent: str = Field(
    description="The strongest argument against this conclusion. Recorded "
    "because a decision that suppressed the counter-argument cannot be reviewed.",
)
```

A conclusion that hides its counter-argument is worth less than one that states it,
because the reviewer cannot check the reasoning without it.

## What is still missing

The honest position: this repository has the room, the routing and the containment.
It does not yet have the measured comparison — the same golden set run through both
paths with accuracy, cost, p95 latency and *output variance across repeated runs*
side by side. That is what would turn the argument above from a design rationale
into a finding, and it is listed as deferred in the
[roadmap](../roadmap.md) rather than quietly implied.

The hypothesis worth testing publicly, when that lands: emergence buys something on
the ambiguous tail and loses badly on cost and determinism everywhere else. The
architecture is built on the assumption it is true. Assumptions should be measured.

---

*Code: [`packages/deliberation`](../../packages/deliberation/),
[`packages/policy/src/backstop_policy/rules.py`](../../packages/policy/src/backstop_policy/rules.py),
[`packages/core-graph/src/backstop_graph/graph.py`](../../packages/core-graph/src/backstop_graph/graph.py).*
