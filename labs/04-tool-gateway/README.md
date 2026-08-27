# Lab 04 — The tool gateway

## Feel the problem first

Run the broken version:

```bash
uv run python labs/04-tool-gateway/start_here.py
```

An agent resolves a ticket, calls `issue_refund`, and the process dies before the
result is recorded. It restarts, replays from where it left off, and calls
`issue_refund` again.

The customer is refunded twice. Nothing errored. Nothing in the output looks wrong.

That failure is not exotic — it is what happens every time a retry lands on a call
that actually succeeded. A timeout on a successful call is indistinguishable, from
the caller's side, from a failure.

## Build the guard

Fill in the four checks in `start_here.py`, in this order:

1. **Scope.** The caller holds a set of capabilities. A tool the caller has no
   scope for is refused *before* it is invoked, not after.
2. **Idempotency.** Derive a key from `(ticket_id, tool, canonical(args))` and
   remember the result. A second call bearing the same key must not reach the
   handler.
3. **Approval.** Above a ceiling, the call needs a signed token bound to the
   ticket, the tool and a digest of the arguments — an approval for €20 must not
   be reusable for €2,000.
4. **Audit.** Append an entry for every attempt, including the refusals.

Then run:

```bash
uv run python labs/04-tool-gateway/check.py
```

## Things worth getting wrong first

**Taking the idempotency key from the caller.** A caller that gets it wrong — or
wants to — defeats the whole mechanism. Derive it.

**Checking approval before idempotency.** A crash-and-resume replays a call whose
approval may since have expired. Replay is the safe path: the approval was already
verified when the call first ran. Get the order backwards and you build a system
that refuses to finish tickets after a restart.

**Recording only successes.** An attacker probing your tool surface produces a run
of refusals and nothing else. A log of what worked shows nothing at all.

## The solution

[`packages/toolgateway/src/backstop_toolgateway/gateway.py`](../../packages/toolgateway/src/backstop_toolgateway/gateway.py).
Read it after you have attempted this — the order of the checks in `invoke()` is
the answer to a question you should have asked yourself first.
