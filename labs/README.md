# Labs

Fifteen exercises that build Backstop from an empty directory. Each one solves a
problem the previous one made you feel — you do not learn about the tool gateway
before an agent has refunded the same customer twice in front of you.

Every lab has the same shape:

```
labs/NN-slug/
  README.md      what you are building, and why it is not obvious
  start_here.py  the code you edit, with the interesting parts removed
  check.py       an acceptance check you run until it passes
```

Run a lab's check with:

```bash
uv run python labs/04-tool-gateway/check.py
```

Nothing in `labs/` is imported by the system. They are allowed to be wrong in
instructive ways.

---

## Track A — The tool plane

| | Lab | The problem it makes you feel |
|---|---|---|
| 01 | Architecture and environment | Where everything sits, before writing agent code. |
| 02 | Your first MCP server | Why a tool protocol beats a hard-coded function. |
| 03 | Retrieval as a tool | Why citation granularity decides whether groundedness checking is possible at all. |
| **04** | **The tool gateway** | **Give an agent `issue_refund` with no guard. Watch it double-refund on a retry.** |

## Track B — Orchestration

| | Lab | The problem it makes you feel |
|---|---|---|
| 05 | A graph, not a loop | Compare a state machine and a ReAct loop on the same tickets. |
| 06 | Durable execution | Kill the process mid-ticket. Resume. Understand why checkpointing is correctness. |
| **07** | **Human in the loop** | **Design the threshold. When is a person worth the latency?** |
| 08 | Multi-agent deliberation | Build the room, then measure honestly whether it earned its cost. |

## Track C — Security

| | Lab | The problem it makes you feel |
|---|---|---|
| 09 | PII you can put back | Tokenise, carry, detokenise. Prove nothing leaked. |
| **10** | **Direct prompt injection** | **Attack your own agent. Measure attack success rate honestly.** |
| **11** | **Indirect injection** | **Plant a payload in a retrieved review. Discover input filtering never sees it.** |
| 12 | Containment | Sandbox the tool runtime. Try to exfiltrate. Fail at the network boundary. |

## Track D — Governance and delivery

| | Lab | The problem it makes you feel |
|---|---|---|
| 13 | Evaluation you can trust | Validate the judge before trusting it. |
| **14** | **Provable decisions** | **Hash-chain the log. Tamper with it. Watch the verifier catch you.** |
| 15 | Gates that hold | Weaken a guardrail in a PR and watch CI refuse it. |

**Bold labs ship with working code and a check.** The rest have a README and are
built from the corresponding package in this repository — the source is the
solution, and reading it after attempting the exercise is the point.

---

## The companion write-ups

Longer pieces in [`docs/lessons/`](../docs/lessons/), each standing alone:

| Lesson | Question it answers |
|---|---|
| [Indirect injection](../docs/lessons/indirect-injection.md) | The attack input filtering structurally cannot catch |
| [Determinism vs emergence](../docs/lessons/determinism-vs-emergence.md) | When is a multi-agent debate worth its cost? |
| [Audit that holds up](../docs/lessons/audit-that-holds-up.md) | What a defensible AI decision record actually contains |
