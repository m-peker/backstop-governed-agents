# Curriculum

Fifteen exercises that build Backstop from an empty directory, ordered so that every
new layer solves a problem the previous one made you feel. You do not learn about
the tool gateway before an agent has refunded the same customer twice in front of
you.

> **What exists today.** The lab framework and one complete lab — 04, the tool
> gateway — ship with runnable code and an acceptance check. The rest have an
> outline here and are built from the corresponding package in this repository:
> the source is the solution, and reading it *after* attempting the exercise is
> the point. [`labs/README.md`](../labs/README.md) says which is which.

## Track A — The tool plane

### Lab 01 · Architecture and environment
Stand up Postgres, Redis and the API. Read a trace in Langfuse. Understand where every
component sits before writing agent code.

### Lab 02 · Your first MCP server
Build `mcp-orders` from scratch: tool definitions, typed arguments, error semantics.
Inspect it with MCP Inspector. Understand why MCP exists rather than hard-coded functions.

### Lab 03 · Retrieval as a tool
Build `mcp-policy` over pgvector. Chunking strategy for legal-ish text, clause-level ids,
and why citation granularity determines whether groundedness checking is even possible.

### Lab 04 · The tool gateway
Give an agent `issue_refund` with no guard. Watch it double-refund on a retry. Then build
scopes, idempotency keys, rate limits and audit emission. Feel the problem first.

---

## Track B — Orchestration

### Lab 05 · A graph, not a loop
Model the resolution flow as a LangGraph state machine. Typed state, conditional edges,
concurrent fan-out. Contrast with a naive ReAct loop on the same tickets.

### Lab 06 · Durable execution
Add the Postgres checkpointer. Kill the process mid-ticket. Resume. Understand why
checkpointing is a correctness requirement, not an optimization.

### Lab 07 · Human in the loop
Implement approval with `interrupt()`. Build the approval queue and the resume endpoint.
Design the threshold policy: when is a human actually worth the latency?

### Lab 08 · Multi-agent deliberation
Build the AutoGen room. Four roles, read-only scopes, bounded rounds, a structured verdict.
Then measure it against the graph and decide honestly whether it earned its cost.

---

## Track C — Security

### Lab 09 · PII you can put back
Detect and tokenize personal data, including Turkish identifiers. Carry tokens through the
whole pipeline and detokenize only at an authorized channel. Prove no token leaked.

### Lab 10 · Direct prompt injection
Attack your own agent. Instruction override, role play, delimiter escape, encoding tricks,
multilingual payloads. Build layered detection and measure attack success rate honestly.

### Lab 11 · Indirect injection
The hard one. Plant a hostile instruction inside a product review that the policy RAG
retrieves. Discover that input filtering never sees it. Learn spotlighting, provenance
tagging and why deterministic output re-checking is the only real control.

### Lab 12 · Containment
Sandbox the tool runtime: non-root, read-only filesystem, egress allowlist, no shell.
Attempt exfiltration through a tool and watch it fail at the network boundary.

---

## Track D — Governance and delivery

### Lab 13 · Evaluation you can trust
Build the golden set. Write an LLM-as-judge rubric and measure the judge's own agreement
with itself and with you. Learn why an unvalidated judge is worse than no judge.

### Lab 14 · Provable decisions
Hash-chain the audit log. Build the verifier. Version prompts and pin their hashes. Export
a decision dossier and answer the question "why did the system refund this customer?"
without reading any code.

### Lab 15 · Gates that hold
Wire the eval, red-team, cost and governance gates into GitHub Actions. Open a pull request
that quietly weakens a guardrail and watch CI refuse it. Ship a canary and roll it back.

---

## Companion write-ups

Longer-form pieces, each standing alone. These are the parts to read if you only
read one thing.

| Lesson | Question it answers |
|---|---|
| [Indirect injection](lessons/indirect-injection.md) | The attack that input filtering structurally cannot catch |
| [Determinism vs emergence](lessons/determinism-vs-emergence.md) | When is a multi-agent debate worth its cost? |
| [Audit that holds up](lessons/audit-that-holds-up.md) | What a defensible AI decision record actually contains |

Three more are outlined and unwritten: why a tool protocol beats framework-native
bindings, how to validate an LLM judge before trusting it, and translating the EU
AI Act into code-level controls.
