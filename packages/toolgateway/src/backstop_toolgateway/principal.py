"""Who is calling.

A principal is a named agent role with a fixed set of scopes. Roles are declared
here rather than assembled at call time, because a capability set that is built
dynamically is a capability set nobody can review.

The important entries are the deliberation roles. Every agent in the AutoGen room
is read-only. The room argues about what should happen; it cannot make anything
happen. Only :data:`GRAPH_EXECUTOR`, reached from a single node in the resolution
graph after the risk gate, holds ``payments:write``.
"""

from __future__ import annotations

from dataclasses import dataclass

from backstop_toolgateway.scopes import READ_ONLY, Scope


@dataclass(frozen=True, slots=True)
class Principal:
    """An agent role and the capabilities it holds."""

    id: str
    label: str
    scopes: frozenset[Scope]

    def holds(self, scope: Scope) -> bool:
        return scope in self.scopes

    @property
    def is_read_only(self) -> bool:
        return not any(scope is Scope.PAYMENTS_WRITE for scope in self.scopes)


#: Gathers facts. Reads everything, writes nothing.
GRAPH_INVESTIGATOR = Principal(
    id="graph:gather_facts",
    label="Resolution graph, fact gathering",
    scopes=READ_ONLY,
)

#: Retrieves policy only. Narrower than it needs to be on purpose: the node that
#: retrieves clauses has no reason to read customer data, so it cannot.
GRAPH_POLICY_READER = Principal(
    id="graph:policy_retrieval",
    label="Resolution graph, policy retrieval",
    scopes=frozenset({Scope.POLICY_READ}),
)

#: The only principal in the system that can move money.
GRAPH_EXECUTOR = Principal(
    id="graph:execute",
    label="Resolution graph, execution",
    scopes=frozenset({Scope.PAYMENTS_WRITE, Scope.PAYMENTS_READ, Scope.ORDERS_READ}),
)

#: Deliberation roles. All read-only, all of them.
DELIBERATION_POLICY_ANALYST = Principal(
    id="deliberation:policy_analyst",
    label="Deliberation room, policy analyst",
    scopes=frozenset({Scope.POLICY_READ, Scope.CATALOG_READ}),
)

DELIBERATION_CUSTOMER_ADVOCATE = Principal(
    id="deliberation:customer_advocate",
    label="Deliberation room, customer advocate",
    scopes=frozenset({Scope.ORDERS_READ, Scope.POLICY_READ}),
)

DELIBERATION_FRAUD_INVESTIGATOR = Principal(
    id="deliberation:fraud_investigator",
    label="Deliberation room, fraud investigator",
    scopes=frozenset({Scope.ORDERS_READ, Scope.SHIPPING_READ, Scope.PAYMENTS_READ}),
)

DELIBERATION_ARBITER = Principal(
    id="deliberation:arbiter",
    label="Deliberation room, arbiter",
    scopes=frozenset({Scope.POLICY_READ}),
)

#: Every declared principal, for tests and for the governance dashboard.
ALL_PRINCIPALS: tuple[Principal, ...] = (
    GRAPH_INVESTIGATOR,
    GRAPH_POLICY_READER,
    GRAPH_EXECUTOR,
    DELIBERATION_POLICY_ANALYST,
    DELIBERATION_CUSTOMER_ADVOCATE,
    DELIBERATION_FRAUD_INVESTIGATOR,
    DELIBERATION_ARBITER,
)


__all__ = [
    "ALL_PRINCIPALS",
    "DELIBERATION_ARBITER",
    "DELIBERATION_CUSTOMER_ADVOCATE",
    "DELIBERATION_FRAUD_INVESTIGATOR",
    "DELIBERATION_POLICY_ANALYST",
    "GRAPH_EXECUTOR",
    "GRAPH_INVESTIGATOR",
    "GRAPH_POLICY_READER",
    "Principal",
]
