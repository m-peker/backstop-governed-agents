# ADR 0001 — Record architecture decisions

- Status: accepted
- Date: 2026-08-25

## Context

This repository is both a working system and a teaching artifact. A reader needs to know
not only what was built but why the alternatives were rejected.

## Decision

Every non-obvious architectural choice gets an ADR before the implementing code merges.
Format: context, decision, consequences, alternatives considered. ADRs are immutable once
accepted; a reversal is a new ADR that supersedes the old one.

## Consequences

- Reviewers can reconstruct the reasoning without reading the diff history.
- CI checks that any PR touching `packages/*/src` either references an existing ADR or adds one.
