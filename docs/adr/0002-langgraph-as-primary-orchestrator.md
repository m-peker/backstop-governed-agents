# ADR 0002 — LangGraph as the primary orchestrator

- Status: accepted
- Date: 2026-08-25

## Context

Resolving a customer ticket can move money. The flow must be inspectable, resumable across
days of waiting on a human, and identical on every run for identical input.

## Decision

The primary path is a LangGraph state machine with a Postgres checkpointer. AutoGen is used
only for the ambiguous tail and never terminates a ticket; it returns a structured verdict
into the graph.

## Consequences

- Control flow is code, reviewable in a diff, and diagrammable.
- Human approval is a first-class `interrupt()` rather than an application-level hack.
- A crash mid-ticket resumes from the last checkpoint instead of replaying side effects.
- Cost: more upfront design than an agent loop. Accepted deliberately.

## Alternatives considered

- **A single ReAct loop.** Cheapest to write, impossible to audit or resume. Rejected.
- **AutoGen for everything.** Non-deterministic control flow over a money-moving action.
  Rejected as the primary path, retained for the tail.
- **A hand-rolled state machine.** No checkpointing, no streaming, no ecosystem tooling.
