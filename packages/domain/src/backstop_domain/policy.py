"""The policy corpus.

Policy documents are Markdown with YAML front matter. Each clause is numbered and
addressable - ``RP-4.2``, ``DP-5.3`` - and the parser preserves that structure.

Clause-level addressing is not a cosmetic choice. It is what makes groundedness
checking possible: an agent that says "the customer is entitled to a full refund"
must cite the clause that says so, and the output guardrail can verify the clause
exists, was actually retrieved for this ticket, and says something on the subject.
Retrieval that returned whole documents would make that check meaningless, because
any document contains a sentence for every conclusion.

The corpus also carries :class:`Ambiguity` records: deliberate contradictions
planted across the documents, loaded from ``ambiguities.yaml``. They are ground
truth for the evaluation harness and are never exposed through a tool.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from backstop_domain.models import ClauseId

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECTION = re.compile(r"^##\s+([A-Z]{2}-\d+)\s+(.+?)\s*$")
_CLAUSE = re.compile(r"^\*\*([A-Z]{2}-\d+\.\d+)\*\*\s*(.*)$")
_EMPHASIS = re.compile(r"\*{1,2}(.+?)\*{1,2}")


def _plain(text: str) -> str:
    """Strip Markdown emphasis.

    The clause text is what reaches a model context and an audit entry, so it
    should be prose, not source. Leaving ``**`` in place also corrupts lexical
    retrieval, since the tokenizer would split an emphasised term differently
    from a plain one.
    """
    return _EMPHASIS.sub(r"\1", text)


class ExpectedBehaviour(StrEnum):
    """What the system should do when an ambiguity is engaged."""

    DELIBERATE = "deliberate"
    """Route to the multi-agent room: the clauses genuinely pull in two directions."""

    ESCALATE = "escalate"
    """Hand to a human: the text does not authorise an automated answer."""

    POLICY_ENGINE_BINDS = "policy_engine_binds"
    """Deterministic code decides, whatever the prose appears to permit."""


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PolicyClause(Frozen):
    id: ClauseId
    document_id: str
    section_id: str = Field(pattern=r"^[A-Z]{2}-\d+$")
    section_title: str
    text: str
    ordinal: int = Field(ge=0, description="Position within the document, for stable ordering")

    @property
    def citation(self) -> str:
        return f"{self.id} ({self.section_title})"


class PolicyDocument(Frozen):
    document_id: str
    title: str
    prefix: str = Field(min_length=2, max_length=2)
    version: str
    effective_from: str
    owner: str
    clauses: tuple[PolicyClause, ...]


class Ambiguity(Frozen):
    """A planted contradiction. Ground truth, never exposed by a tool."""

    id: str = Field(pattern=r"^AMB-\d{2}$")
    name: str
    clauses: tuple[ClauseId, ...] = Field(min_length=2)
    situation: str
    why_ambiguous: str
    expected_behaviour: ExpectedBehaviour
    must_not: tuple[str, ...] = ()
    note: str = ""


class PolicyCorpus(Frozen):
    """Every document, indexed for lookup."""

    documents: tuple[PolicyDocument, ...]
    ambiguities: tuple[Ambiguity, ...] = ()

    @property
    def clauses(self) -> tuple[PolicyClause, ...]:
        return tuple(clause for document in self.documents for clause in document.clauses)

    def get_clause(self, clause_id: str) -> PolicyClause | None:
        return next((clause for clause in self.clauses if clause.id == clause_id), None)

    def get_section(self, section_id: str) -> tuple[PolicyClause, ...]:
        return tuple(clause for clause in self.clauses if clause.section_id == section_id)

    def get_document(self, document_id: str) -> PolicyDocument | None:
        return next(
            (document for document in self.documents if document.document_id == document_id),
            None,
        )

    def ambiguities_for(self, clause_id: str) -> tuple[Ambiguity, ...]:
        return tuple(item for item in self.ambiguities if clause_id in item.clauses)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_document(source: str) -> PolicyDocument:
    """Parse one Markdown policy document.

    Raises:
        ValueError: on missing front matter, an unknown clause prefix, or a clause
            that appears before any section heading. These are authoring errors
            and should fail loudly rather than silently drop a clause - a policy
            clause that is never indexed is a clause an agent can never cite.
    """
    match = _FRONT_MATTER.match(source)
    if match is None:
        raise ValueError("policy document is missing YAML front matter")

    meta: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
    required = ("document_id", "title", "prefix", "version", "effective_from", "owner")
    missing = [key for key in required if key not in meta]
    if missing:
        raise ValueError(f"front matter is missing {', '.join(missing)}")

    prefix = str(meta["prefix"])
    body = source[match.end() :]

    clauses: list[PolicyClause] = []
    section_id = ""
    section_title = ""
    pending_id: str | None = None
    pending_lines: list[str] = []

    def flush() -> None:
        nonlocal pending_id, pending_lines
        if pending_id is None:
            return
        text = _plain(" ".join(line.strip() for line in pending_lines if line.strip()))
        clauses.append(
            PolicyClause(
                id=pending_id,
                document_id=str(meta["document_id"]),
                section_id=section_id,
                section_title=section_title,
                text=text,
                ordinal=len(clauses),
            )
        )
        pending_id = None
        pending_lines = []

    for raw_line in body.splitlines():
        section_match = _SECTION.match(raw_line)
        if section_match:
            flush()
            section_id, section_title = section_match.group(1), section_match.group(2)
            continue

        clause_match = _CLAUSE.match(raw_line)
        if clause_match:
            flush()
            clause_id, first_line = clause_match.group(1), clause_match.group(2)
            if not clause_id.startswith(f"{prefix}-"):
                raise ValueError(f"clause {clause_id} does not match the document prefix {prefix}")
            if not section_id:
                raise ValueError(f"clause {clause_id} appears before any section heading")
            pending_id = clause_id
            pending_lines = [first_line]
            continue

        if pending_id is not None:
            pending_lines.append(raw_line)

    flush()

    if not clauses:
        raise ValueError(f"policy document {meta['document_id']} contains no clauses")

    return PolicyDocument(
        document_id=str(meta["document_id"]),
        title=str(meta["title"]),
        prefix=prefix,
        version=str(meta["version"]),
        effective_from=str(meta["effective_from"]),
        owner=str(meta["owner"]),
        clauses=tuple(clauses),
    )


def load_corpus(directory: Path) -> PolicyCorpus:
    """Load every ``*.md`` policy in a directory, plus ``ambiguities.yaml``."""
    documents = [
        parse_document(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.md"))
    ]
    if not documents:
        raise ValueError(f"no policy documents found in {directory}")

    ambiguities: tuple[Ambiguity, ...] = ()
    ambiguity_path = directory / "ambiguities.yaml"
    if ambiguity_path.exists():
        payload = yaml.safe_load(ambiguity_path.read_text(encoding="utf-8")) or {}
        ambiguities = tuple(Ambiguity(**item) for item in payload.get("ambiguities", []))

    corpus = PolicyCorpus(documents=tuple(documents), ambiguities=ambiguities)
    _assert_ambiguities_cite_real_clauses(corpus)
    return corpus


def _assert_ambiguities_cite_real_clauses(corpus: PolicyCorpus) -> None:
    """An ambiguity pointing at a clause that does not exist is a broken label.

    Cheap to check on load, and it catches the common authoring mistake of
    renumbering a clause without updating the eval ground truth.
    """
    known = {clause.id for clause in corpus.clauses}
    for ambiguity in corpus.ambiguities:
        unknown = [clause_id for clause_id in ambiguity.clauses if clause_id not in known]
        if unknown:
            raise ValueError(f"{ambiguity.id} cites unknown clauses: {', '.join(unknown)}")


#: Default location of the policy corpus, relative to the repository root.
DEFAULT_POLICY_DIR = Path("seed-data/policies")


__all__ = [
    "DEFAULT_POLICY_DIR",
    "Ambiguity",
    "ExpectedBehaviour",
    "PolicyClause",
    "PolicyCorpus",
    "PolicyDocument",
    "load_corpus",
    "parse_document",
]
