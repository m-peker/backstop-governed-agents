# What a defensible AI decision record actually contains

"We log everything" is the usual answer, and it is not one. Logs are prose written
by developers for developers, they rotate, and nothing about them survives someone
with database access deciding a particular line is inconvenient.

The question a regulator, an auditor or a customer's lawyer actually asks is
narrower and harder: **why did this system refund this customer, and how do I know
that record is what it was when the decision was made?**

Answering it takes four things, and only one of them is a log.

## 1. Every capability use, including the refusals

The audit chain records an entry for every call through the tool gateway, whatever
happened to it:

| outcome | meaning |
|---|---|
| `allowed` | it ran |
| `refused` | a control stopped it — scope, ceiling, kill switch, rate limit |
| `failed` | it ran and raised |
| `replayed` | the idempotency key matched an earlier call; the stored result was returned |

The refusals are the part people leave out, and they are the part that carries the
signal. An attacker probing the tool surface produces a long run of `scope_denied`
entries. A log that only recorded what worked would show nothing at all — the
probing would be invisible precisely because it failed.

## 2. Arguments as digests, not in the clear

Every entry carries `args_digest`: a SHA-256 over the canonical serialisation of the
arguments, and never the arguments themselves.

This is not squeamishness. Tool arguments carry order identifiers, amounts and, in a
system that touches personal data, worse. An audit log that copies every payload
becomes its own disclosure problem — you have built a second, less protected store
of exactly the data the rest of the system is careful with.

The digest keeps what matters. Anyone holding the arguments can prove they were the
ones used. Nobody reading the log learns them.

## 3. A chain, so tampering is visible

Each entry carries the hash of the one before it:

```python
entry_hash = sha256(previous_hash ‖ canonical_json(payload))
```

Edit a past entry and its hash no longer reconciles. Delete one and the next entry's
`previous_hash` points at nothing. The verifier walks the chain and names the first
entry that does not add up.

This is tamper-*evidence*, not tamper-*prevention*, and the difference is worth
being precise about. Someone with database access can still delete a row. They
cannot do it without the chain saying so.

Getting this right has one subtlety that cost a real bug here. The first version
computed the hash from a dict built alongside the entry, while `verify()` recomputed
it from the entry's own serialisation. Two serialisations of "the same" payload —
a datetime rendered one way here and another way by the model serialiser — and the
chain would have failed to verify against data nobody had touched. There is now one
source of truth, hashed once:

```python
draft = AuditEntry(..., entry_hash="")
entry = draft.model_copy(update={"entry_hash": chain_hash(previous, draft.payload())})
```

A verifier that produces false positives gets disabled within a week, and then you
have no verifier.

## 4. Which model, which prompt, which clauses

The chain says what the system *did*. A decision record also has to say what it was
*thinking with*, and that means three registries.

**The prompt registry.** Prompts are versioned artefacts with an owner, a changelog
and a content hash pinned in a lock file. Editing one without bumping its version
fails CI — because every dossier written before the edit would otherwise cite a
version that no longer says what it said. This is not hypothetical: it fired during
development, when a prompt was corrected after a model reproduced a spotlight
delimiter, and the gate refused the change until the version moved to `1.1.0` and
the changelog explained why.

**The model, per call.** Every completion records the model id the provider actually
returned — not the one that was requested — plus tokens and normalised USD cost. The
`fell_back_from` field records a failover, so "which model decided this" stays
answerable on the day the primary provider was down.

**The clauses.** Every resolution cites the policy clauses it rests on, and the
output guardrail verifies each one was actually retrieved for that ticket. A model
that wants to reach a conclusion has to name where it came from, and a fabricated
clause number never reaches the customer.

## What it looks like assembled

```
seq  outcome    principal                   tool                      detail
0    allowed    graph:gather_facts          get_order                 5.6ms
1    allowed    graph:gather_facts          get_customer_profile
2    allowed    graph:gather_facts          track_shipment            1.0ms
3    allowed    graph:policy_retrieval      search_policy             9.2ms
4    refused    graph:execute               issue_refund              approval_required
5    allowed    graph:execute               issue_refund
6    replayed   graph:execute               issue_refund
7    allowed    graph:execute               get_movements_for_order
8    refused    deliberation:customer_advocate  issue_refund          scope_denied

entries          9
chain verified   yes
```

Read line 4 and 5 together: the system tried to refund, was refused because the
amount was over the ceiling, and succeeded only after a signed approval bound to
those exact arguments. Line 6 is a replay after a crash — the customer was paid
once. Line 8 is a read-only role being refused a capability it never held.

That is a decision record. Not because it is long, but because every claim in it can
be checked by someone who does not trust the people who wrote the system.

## The demonstration

`make demo` ends by tampering with the record on purpose:

```
8. Tampering with the record
  verifier says     entry 0 has been modified
```

An audit chain nobody has ever seen fail is an audit chain nobody has tested.

---

*Code: [`packages/toolgateway/src/backstop_toolgateway/audit.py`](../../packages/toolgateway/src/backstop_toolgateway/audit.py),
[`packages/toolgateway/src/backstop_toolgateway/canonical.py`](../../packages/toolgateway/src/backstop_toolgateway/canonical.py),
[`packages/core-graph/src/backstop_graph/prompts.py`](../../packages/core-graph/src/backstop_graph/prompts.py).
Run it: `make demo`, `make governance`.*
