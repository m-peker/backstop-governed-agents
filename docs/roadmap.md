# Roadmap

Ten phases. Each one ends with something that runs, is demoable, and is worth talking about
in an interview. If the project stops after any phase, what exists still stands on its own.

Estimates assume a few evenings a week.

---

## Phase 0 — Foundation
**status: complete**

- Monorepo layout: `uv` workspace for Python, npm workspace for the console.
- `docker compose`: Postgres 16 + pgvector, Redis, OTel collector, Prometheus,
  Grafana, and Langfuse behind a profile.
- FastAPI service: settings split into operational and governance halves, lazily
  constructed resources, liveness, readiness and a governance posture endpoint.
- One log stream: structlog through the standard library so application and
  third-party records render identically, every line carrying `trace_id`.
- OpenTelemetry bootstrap with the span attribute convention the dashboards rely on.
- Console posture page rendering the controls currently in force.
- Two developer runners, `Makefile` and `task.ps1`, held in parity by CI.
- `ci.yml`: ruff, `mypy --strict`, pytest, console typecheck/lint/build, compose
  validation, task parity.

**Demoable:** `make up && make dev` gives a traced service that reports what it is
allowed to do. Without Docker it degrades honestly rather than crashing.

---

## Phase 1 — Domain and tool plane
**status: complete**

- Deterministic dataset generator: 120 products, 500 customers, 2,000 orders, 1,941
  shipments, 259 returns, and 22 planted abuse patterns with ground-truth labels.
- Money is `Decimal` throughout; Turkish-aware text folding so `İ`, `I` and `ı`
  cannot split one address into two.
- Three policy documents, 81 addressable clauses, and seven deliberate
  contradictions recorded in `ambiguities.yaml` as eval ground truth.
- Clause-level BM25 retrieval - deterministic, offline, no embeddings. Dense
  retrieval fuses in alongside it in Phase 2.
- Five MCP servers over one `DomainStore` Protocol, plus an in-process bridge to
  the gateway.
- Tool gateway: scope registry, kill switch, HMAC approval tokens bound to ticket,
  tool and argument digest, derived idempotency keys, token-bucket rate limits, and
  a hash-chained audit log that records refusals as carefully as successes.

**Demoable:** `make demo` resolves a real ticket end to end - gather facts, retrieve
policy, hit the approval gate, resume with a signed approval, survive a replay
without double-refunding, watch a read-only role be refused, then verify the audit
chain and watch it detect a tampered row.

---

## Phase 2 — The resolution graph
**status: complete**

- `ResolutionState`: every field JSON-serialisable, because the state is
  checkpointed after each node and anything that cannot survive the round trip
  cannot live there.
- Eleven nodes, conditional edges, and a routing table that is readable in one
  file. `interrupt()`-based human approval: the graph stops, the request lands in
  a queue, and a resume call rehydrates the checkpoint.
- `gather_facts` fans out to the tool plane concurrently and degrades honestly - a
  tool that fails records a gap, and the assessment prompt is told what is missing.
- A versioned prompt registry. Code refers to prompts by `name@version` and an
  unknown pair raises rather than falling back to "latest".

**Demoable:** a ticket flows end to end, pauses for approval, resumes.

**Deferred:** the Postgres checkpointer and `PostgresStore` (see ADR 0005 - the
in-memory store keeps every lab runnable without Docker); dense retrieval over
pgvector; SSE streaming of node transitions.

---

## Phase 3 — Guardrail plane
**status: complete**

- Normalisation first: zero-width and bidi controls stripped, homoglyphs folded,
  NFKC applied, length capped. Every change is reported, never silent - an audit
  record of a rewritten message is a record of something nobody wrote.
- PII tokenisation with checksum-validated Turkish identifiers (TCKN, IBAN, Luhn).
  Tokenised, not redacted, so the reply can still address the customer by name.
- Layered injection detection - structure, lexical, density - plus a per-ticket
  canary in the system prompt. Two independent layers agreeing is what blocks;
  one alone escalates.
- Output pass: schema, groundedness against retrieved clauses, a deterministic
  policy re-check, a PII leak scan, and detokenisation only for an authorised
  channel.
- Every detector has a false-positive test. A guardrail that blocks angry
  customers is an outage, not a safety feature.

**Demoable:** `make redteam` - 21 attacks and benign controls, 0% attack success.

**Deferred:** container sandboxing for the tool runtime (non-root, read-only
rootfs, egress allowlist). The scopes and the gateway carry containment today.

---

## Phase 4 — Deliberation and the comparison
**status: complete**

- AutoGen `RoundRobinGroupChat` with three arguing roles and a separate arbiter
  that reads the transcript rather than participating in it.
- Every AutoGen model call routes through the Backstop client, so the room's spending
  reaches the same ledger, the same budget ceiling and the same span as everything
  else. AutoGen orchestrates; Backstop meters.
- Containment: read-only principals, no tool calling at all, a hard message cap,
  and a budget that stops a long argument.
- The room is convened by the *policy engine*, not the graph: a ruling flagged
  ambiguous means the clauses genuinely conflict and are worth arguing. A plain
  ceiling case goes straight to the queue. There is no edge from `deliberate` to
  `execute`, and that absence is the guarantee.

**Demoable:** an AMB-01 ticket convenes the room and the reviewer receives both
sides plus the recorded dissent.

**Deferred:** `docs/engine-comparison.md` - the measured trade-off between the
deterministic path and the debate across the same golden set, including output
variance over repeated runs. The harness exists; the write-up does not.

---

## Phase 5 — Evaluation harness
**status: complete**

- A red-team corpus of 21 entries across ten attack families plus benign controls,
  each recording two separate expectations: whether detection *should* notice, and
  what would count as an actual breach. The gate is on the second.
- A golden set of labelled scenarios bound at run time to real dataset records, so
  the labels are true by construction rather than annotated after the fact.
- Escalation scored in both directions. A system that escalates everything is
  perfectly safe and useless, and a metric that only counted misses would call it
  a success.
- Unsafe actions counted separately with a threshold of zero. Accuracy is
  negotiable; a refund that should never have been paid is not.
- Both runners work offline and free. A security suite that needed a live model to
  tell you whether your controls held would be measuring the wrong thing.

**Demoable:** `make evals` and `make redteam`, both green, both costing nothing.

**Deferred:** LLM-as-judge scoring of reply quality with a validated rubric; an
HTML report; committed trend history. The golden set is 10 scenarios, not 200.

---

## Phase 6 — Governance plane
**status: complete**

- Hash-chained audit log with canonical JSON and a verifier. Editing or deleting a
  past entry is detected; the demo does exactly that and shows the verifier catching it.
- Prompt registry with content hashes pinned in a lock file. Editing a prompt
  without bumping its version fails CI, because every dossier written before the
  edit would otherwise claim a version that no longer says what it said.
- Policy-as-code: 18 rules, each naming the clauses it implements, each unit
  tested against the situation in the language of the policy. The planted
  ambiguities are handled explicitly - the engine refers rather than picking a
  reading the text does not support.
- Budget ceiling with a circuit breaker, and a kill switch the gateway checks
  before scopes, before approval, before anything.

**Demoable:** `make governance` - prompt hashes, rule citations and the planted
ambiguities all verified.

**Deferred:** model cards; the EU AI Act classification and NIST AI RMF mapping;
the DPIA; per-ticket decision dossier export. The data every one of them needs is
already recorded - what is missing is the documents and the exporter.

---

## Phase 7 — CI/CD quality gates
**status: complete**

- `ci.yml` - ruff, `mypy --strict`, pytest, console typecheck/lint/build, compose
  validation, and a job that diffs the two developer runners so neither drifts.
- `redteam.yml` - the attack corpus on every pull request that touches a guardrail,
  a prompt or the gateway, plus nightly. Gated on attack success rate and on false
  positives, with a job summary table.
- `evals.yml` - the golden set offline on every relevant pull request, and a live
  run on demand with a budget ceiling. On demand because a gate that costs money
  and flakes is a gate that gets disabled.
- `governance.yml` - prompt hash integrity, rules citing real clauses, planted
  ambiguities intact, and the declared tool surface matching the servers.
- `security.yml` - gitleaks, pip-audit, `npm audit`, CycloneDX SBOM.

**Demoable:** weaken a guardrail in a pull request and watch the red-team gate
refuse it.

**Deferred:** a PR comment showing the score diff against base (the runs write job
summaries today); container image scanning; `release.yml` with canary deploy,
smoke evals and auto-rollback.

---

## Phase 8 — Console
**status: complete**

- Ticket inbox with a submit box that runs the real graph, and a detail view laid
  out in pipeline order - what arrived, what the model saw, what fired, what was
  retrieved, what was proposed, what the policy decided, what the customer got.
- Approval queue. Each item carries the proposed resolution, the clauses, the
  recorded concerns and - where the room sat - both sides of the argument plus the
  dissent, so a reviewer is not reconstructing the case themselves.
- Attack Lab: paste a hostile message, watch each layer fire, and see the exact
  block a model would have received. It analyses and stops - a page built to be fed
  hostile input is not also a way to run it.
- Governance dashboard: controls in force, spend by task, capability use by
  outcome, the prompt registry with hashes, and the audit chain re-verified on
  every request rather than cached.
- The API behind it: `/tickets`, `/approvals`, `/lab/scan`, `/governance/*`, with a
  SQLite checkpointer so a ticket paused for approval survives a restart.

**Demoable:** submit a damaged-item ticket, watch it stop at the ceiling, approve it
in the queue, and read the reply the customer received.

**Deferred:** SSE streaming of node transitions (the detail view is a snapshot, not
a live trace); charts on the governance page; polished screen recordings.

---

## Phase 9 — Curriculum and publication
**status: partial**

- Three write-ups in [`docs/lessons/`](lessons/), each standing alone: the attack
  input filtering structurally cannot catch, when a debate is worth its cost, and
  what a defensible decision record actually contains.
- A lab framework and one complete lab - [lab 04](../labs/README.md), the tool
  gateway - which makes you watch a customer get refunded twice before you build
  the guard that stops it.

**Deferred, and stated plainly:** the other fourteen labs have a README entry and
an outline, not runnable code. The MkDocs site, the exported diagrams and the demo
video are not built. The curriculum is a real start, not a finished course.

---

## Cross-cutting standards

Enforced from Phase 0, not retrofitted:

- Type coverage: `mypy --strict` on all packages; no `Any` at package boundaries.
- Every package has tests. Coverage floor rises each phase and is enforced in CI.
- Every architectural decision gets an ADR before the code lands.
- Every prompt is registered and versioned. Inline prompt strings fail CI.
- No secret ever reaches a log, a trace, or an LLM context.
