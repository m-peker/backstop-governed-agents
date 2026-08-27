"""The capability boundary.

Every tool call an agent makes passes through :meth:`ToolGateway.invoke`. Nothing
reaches an MCP server any other way.

The checks run in a fixed order, and the order is the design:

1. **Is the tool declared?** An undeclared name is refused before anything else.
2. **Is the kill switch engaged?** Checked before scopes, before approval, before
   the registry lookup even matters for writes. A kill switch that runs late is a
   kill switch with exceptions.
3. **Does the principal hold the scope?** Structural. Not influenced by anything
   in the ticket, the arguments, or the model's reasoning.
4. **Is the call within its rate limit?**
5. **Has this exact call already run?** Replay the stored result rather than
   executing twice. This comes *before* approval on purpose: a crash-and-resume
   must not be blocked by an approval that has since expired, because the
   approval was already verified when the call first ran.
6. **Does it need a human, and is there a valid token?** The amount is read from
   the declared argument and compared to the ceiling.
7. **Execute**, then store the result if the tool writes.

Every path appends to the audit chain, including every refusal.

The gateway deliberately knows nothing about *why* a call is being made. It does
not read the ticket text, it does not see the model's reasoning, and it cannot be
argued with. That is the whole point: a model can be persuaded, and this cannot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from backstop_toolgateway.approval import ApprovalAuthority, ApprovalToken
from backstop_toolgateway.audit import AuditChain, Outcome
from backstop_toolgateway.canonical import Clock, system_clock
from backstop_toolgateway.errors import (
    ApprovalRequired,
    GatewayError,
    KillSwitchEngaged,
    RateLimited,
    ScopeDenied,
    ToolExecutionFailed,
    UnknownTool,
)
from backstop_toolgateway.idempotency import (
    IdempotencyStore,
    MemoryIdempotencyStore,
    idempotency_key,
)
from backstop_toolgateway.principal import Principal
from backstop_toolgateway.ratelimit import RateLimiter
from backstop_toolgateway.scopes import DEFAULT_AUTO_APPROVE_CEILING, ToolRegistry, ToolSpec

#: A tool implementation. Receives validated arguments, returns a serialisable
#: result. Handlers know nothing about scopes, approval or auditing.
ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]


class PolicyProvider(Protocol):
    """Governance values the gateway consults on every call.

    A protocol rather than plain settings because these change at runtime: an
    operator flips the kill switch and the very next call must see it.
    """

    def auto_approve_ceiling(self) -> Decimal: ...

    def kill_switch_engaged(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class StaticPolicy:
    """Fixed governance values. Used in tests and in the labs."""

    ceiling: Decimal = DEFAULT_AUTO_APPROVE_CEILING
    kill_switch: bool = False

    def auto_approve_ceiling(self) -> Decimal:
        return self.ceiling

    def kill_switch_engaged(self) -> bool:
        return self.kill_switch


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a successful invocation returns."""

    tool: str
    value: Any
    replayed: bool
    audit_sequence: int
    duration_ms: float


class ToolGateway:
    """Enforces the capability boundary in front of every tool."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        handlers: Mapping[str, ToolHandler],
        approvals: ApprovalAuthority,
        policy: PolicyProvider | None = None,
        audit: AuditChain | None = None,
        idempotency: IdempotencyStore | None = None,
        rate_limiter: RateLimiter | None = None,
        clock: Clock = system_clock,
    ) -> None:
        undeclared = sorted(set(handlers) - set(registry.names()))
        if undeclared:
            raise ValueError("handlers registered for undeclared tools: " + ", ".join(undeclared))

        self._registry = registry
        self._handlers = dict(handlers)
        self._approvals = approvals
        self._policy = policy or StaticPolicy()
        self._clock = clock
        self.audit = audit or AuditChain(clock=clock)
        self._idempotency = idempotency or MemoryIdempotencyStore(clock=clock)
        self._rate_limiter = rate_limiter or RateLimiter(clock=clock)

    # -- public API -------------------------------------------------------

    async def invoke(
        self,
        *,
        principal: Principal,
        ticket_id: str,
        tool: str,
        args: Mapping[str, Any] | None = None,
        approval: ApprovalToken | None = None,
    ) -> ToolResult:
        """Call a tool, or refuse and say why.

        Raises:
            GatewayError: one of its subclasses, each naming a specific refusal.
        """
        arguments: dict[str, Any] = dict(args or {})
        spec = self._registry.get(tool)

        if spec is None:
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope="",
                args=arguments,
                error=UnknownTool(f"no tool named {tool!r} is declared", tool=tool),
            )
            raise UnknownTool(f"no tool named {tool!r} is declared", tool=tool)

        try:
            amount = self._extract_amount(spec, arguments)
        except GatewayError as error:
            # An amount that will not parse is a refusal like any other, and it
            # gets an audit entry like any other. A refusal that leaves no trace
            # is a gap in exactly the record this system exists to produce.
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope=spec.scope.value,
                args=arguments,
                error=error,
                outcome=Outcome.FAILED,
            )
            raise

        try:
            self._check_kill_switch(spec)
            self._check_scope(principal, spec)
            self._check_rate_limit(principal, spec)
        except GatewayError as error:
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope=spec.scope.value,
                args=arguments,
                amount=amount,
                error=error,
            )
            raise

        key = (
            idempotency_key(ticket_id=ticket_id, tool=tool, args=arguments) if spec.write else None
        )

        if key is not None:
            stored = self._idempotency.get(key)
            if stored is not None:
                entry = self.audit.append(
                    ticket_id=ticket_id,
                    principal=principal.id,
                    tool=tool,
                    scope=spec.scope.value,
                    outcome=Outcome.REPLAYED,
                    args=arguments,
                    idempotency_key=key,
                    amount=amount,
                    detail="idempotency key matched an earlier call",
                )
                return ToolResult(
                    tool=tool,
                    value=stored.result,
                    replayed=True,
                    audit_sequence=entry.sequence,
                    duration_ms=0.0,
                )

        try:
            self._check_approval(
                spec=spec,
                ticket_id=ticket_id,
                args=arguments,
                amount=amount,
                approval=approval,
            )
        except GatewayError as error:
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope=spec.scope.value,
                args=arguments,
                amount=amount,
                error=error,
                idempotency_key=key,
                approval=approval.redacted() if approval else None,
            )
            raise

        started = self._clock()
        handler = self._handlers.get(tool)
        if handler is None:
            # A declared tool with no handler: a deployment error, not a caller
            # error. It is still audited, because from the outside it is
            # indistinguishable from a capability being withdrawn mid-flight.
            unbound = ToolExecutionFailed(f"no handler bound for declared tool {tool!r}", tool=tool)
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope=spec.scope.value,
                args=arguments,
                amount=amount,
                error=unbound,
                outcome=Outcome.FAILED,
            )
            raise unbound

        try:
            value = await handler(arguments)
        except Exception as exc:
            failure = ToolExecutionFailed(
                f"tool {tool!r} failed during execution", tool=tool, cause=exc
            )
            self._record_refusal(
                ticket_id=ticket_id,
                principal=principal,
                tool=tool,
                scope=spec.scope.value,
                args=arguments,
                amount=amount,
                error=failure,
                outcome=Outcome.FAILED,
                idempotency_key=key,
                # The upstream message is recorded here, in the audit log, and is
                # not returned to the caller. An operator can read it; a model
                # cannot use it to route around the failure.
                detail=f"{type(exc).__name__}: {exc}",
            )
            raise failure from exc

        duration_ms = round((self._clock() - started).total_seconds() * 1000, 3)

        if key is not None:
            self._idempotency.put(key, ticket_id=ticket_id, tool=tool, result=value)

        entry = self.audit.append(
            ticket_id=ticket_id,
            principal=principal.id,
            tool=tool,
            scope=spec.scope.value,
            outcome=Outcome.ALLOWED,
            args=arguments,
            idempotency_key=key,
            amount=amount,
            approval=approval.redacted() if approval else None,
            duration_ms=duration_ms,
        )

        return ToolResult(
            tool=tool,
            value=value,
            replayed=False,
            audit_sequence=entry.sequence,
            duration_ms=duration_ms,
        )

    def available_tools(self, principal: Principal) -> tuple[ToolSpec, ...]:
        """Tools this principal may call. Use it to build a model's tool list."""
        return self._registry.for_scopes(principal.scopes)

    # -- checks -----------------------------------------------------------

    def _check_kill_switch(self, spec: ToolSpec) -> None:
        if spec.write and self._policy.kill_switch_engaged():
            raise KillSwitchEngaged(
                "the kill switch is engaged; write tools are refused", tool=spec.name
            )

    def _check_scope(self, principal: Principal, spec: ToolSpec) -> None:
        if not principal.holds(spec.scope):
            raise ScopeDenied(
                f"{principal.id} does not hold {spec.scope.value}",
                tool=spec.name,
                required=spec.scope.value,
                held=frozenset(scope.value for scope in principal.scopes),
            )

    def _check_rate_limit(self, principal: Principal, spec: ToolSpec) -> None:
        allowed, retry_after = self._rate_limiter.check(
            principal=principal.id, tool=spec.name, per_minute=spec.rate_limit_per_minute
        )
        if not allowed:
            raise RateLimited(
                f"{spec.name} is limited to {spec.rate_limit_per_minute} calls per minute",
                tool=spec.name,
                retry_after_seconds=retry_after,
            )

    def _check_approval(
        self,
        *,
        spec: ToolSpec,
        ticket_id: str,
        args: dict[str, Any],
        amount: Decimal | None,
        approval: ApprovalToken | None,
    ) -> None:
        ceiling = self._policy.auto_approve_ceiling()
        needs_approval = spec.always_requires_approval or (amount is not None and amount > ceiling)

        if not needs_approval:
            return

        if approval is None:
            raise ApprovalRequired(
                (
                    f"{spec.name} requires human approval"
                    if spec.always_requires_approval
                    else f"{amount} exceeds the automatic approval ceiling of {ceiling}"
                ),
                tool=spec.name,
                amount=amount,
                ceiling=ceiling,
            )

        # Raises ApprovalInvalid on a bad signature, expiry, or any binding
        # mismatch against ticket, tool, arguments or amount.
        self._approvals.verify(
            approval, ticket_id=ticket_id, tool=spec.name, args=args, amount=amount
        )

    @staticmethod
    def _extract_amount(spec: ToolSpec, args: Mapping[str, Any]) -> Decimal | None:
        if spec.amount_argument is None:
            return None
        raw = args.get(spec.amount_argument)
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            # Not the gateway's job to validate the handler's schema, but an
            # unparseable amount must never be treated as "no amount" - that
            # would slip a money-moving call past the ceiling entirely.
            raise ToolExecutionFailed(
                f"{spec.amount_argument} is not a valid amount", tool=spec.name
            ) from None

    # -- auditing ---------------------------------------------------------

    def _record_refusal(
        self,
        *,
        ticket_id: str,
        principal: Principal,
        tool: str,
        scope: str,
        args: dict[str, Any],
        error: GatewayError,
        amount: Decimal | None = None,
        outcome: Outcome = Outcome.REFUSED,
        idempotency_key: str | None = None,
        approval: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        self.audit.append(
            ticket_id=ticket_id,
            principal=principal.id,
            tool=tool,
            scope=scope,
            outcome=outcome,
            args=args,
            idempotency_key=idempotency_key,
            amount=amount,
            approval=approval,
            refusal_code=error.code,
            detail=detail if detail is not None else str(error),
        )


__all__ = ["PolicyProvider", "StaticPolicy", "ToolGateway", "ToolHandler", "ToolResult"]
