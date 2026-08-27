"""Policy MCP server.

Clause-level retrieval over the policy corpus.

Three properties of this server are load-bearing for the rest of the system.

**Results are clauses, not documents.** An agent can only cite what it retrieved,
and the output guardrail can verify a citation against what was actually returned.
Document-level retrieval would make that check vacuous.

**The query surface is fixed.** Text plus an optional document filter, and nothing
else. No free-form predicates, no field selection, no way to ask the index for
everything. This is the tool most exposed to injected instructions - the customer's
own words go into the query - so its blast radius is kept to "returns some
clauses".

**The corpus is versioned and says so.** Every result carries the document version
it came from, because a decision defended six months from now has to be defended
against the policy that was in force at the time.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from backstop_domain.policy import PolicyClause
from backstop_mcp.context import NotFound, clause_index, corpus

server = MCPServer(
    "backstop-policy",
    version="0.1.0",
    instructions=(
        "Retrieval over the returns, delivery and goodwill policies. Read-only. "
        "Results are individual clauses; cite them by id."
    ),
)

#: Hard cap on results. A model handed twenty clauses will find one that supports
#: whatever it already decided.
MAX_RESULTS = 8


def _clause_payload(clause: PolicyClause, *, version: str) -> dict[str, Any]:
    return {
        "clause_id": clause.id,
        "document_id": clause.document_id,
        "document_version": version,
        "section": clause.section_id,
        "section_title": clause.section_title,
        "text": clause.text,
    }


def _version_of(document_id: str) -> str:
    document = corpus().get_document(document_id)
    return document.version if document else "unknown"


@server.tool()
def search_policy(query: str, limit: int = 5, document_id: str | None = None) -> dict[str, Any]:
    """Rank policy clauses against a text query.

    Args:
        query: What to look for, in plain language. Typically the ticket's issue
            plus its classified intent.
        limit: Maximum clauses to return, capped at 8.
        document_id: Optionally restrict to one of ``return-policy``,
            ``delivery-policy`` or ``goodwill-policy``.
    """
    if document_id is not None and corpus().get_document(document_id) is None:
        raise NotFound(f"no policy document with id {document_id}")

    hits = clause_index().search(
        query, limit=min(max(limit, 1), MAX_RESULTS), document_id=document_id
    )

    return {
        "query": query,
        "returned": len(hits),
        # Retrieving nothing is a real answer and is reported as such. An empty
        # result should push the caller to escalate, not to guess.
        "results": [
            {
                **_clause_payload(hit.clause, version=_version_of(hit.clause.document_id)),
                "score": hit.score,
                "matched_terms": list(hit.matched_terms),
            }
            for hit in hits
        ],
    }


@server.tool()
def get_policy_clause(clause_id: str) -> dict[str, Any]:
    """Fetch one clause verbatim by its identifier.

    Use this to read a clause a customer or a colleague referred to by number,
    and to re-read a clause before relying on it.

    Args:
        clause_id: Clause identifier, for example RP-4.2 or DP-3.1.
    """
    clause = corpus().get_clause(clause_id)
    if clause is None:
        raise NotFound(f"no policy clause with id {clause_id}")

    return _clause_payload(clause, version=_version_of(clause.document_id))


@server.tool()
def get_policy_section(section_id: str) -> dict[str, Any]:
    """Every clause in one section, in order.

    Useful when a clause plainly depends on its neighbours - RP-5.3 makes little
    sense without RP-5.4 beside it.

    Args:
        section_id: Section identifier, for example RP-5 or DP-3.
    """
    clauses = corpus().get_section(section_id)
    if not clauses:
        raise NotFound(f"no policy section with id {section_id}")

    version = _version_of(clauses[0].document_id)
    return {
        "section_id": section_id,
        "section_title": clauses[0].section_title,
        "document_id": clauses[0].document_id,
        "document_version": version,
        "clauses": [_clause_payload(clause, version=version) for clause in clauses],
    }


@server.tool()
def list_policy_documents() -> dict[str, Any]:
    """The documents in force, with versions and effective dates."""
    return {
        "documents": [
            {
                "document_id": document.document_id,
                "title": document.title,
                "prefix": document.prefix,
                "version": document.version,
                "effective_from": document.effective_from,
                "owner": document.owner,
                "clause_count": len(document.clauses),
            }
            for document in corpus().documents
        ]
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
