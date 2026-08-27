"""Clause retrieval.

A lexical BM25 index over policy clauses. No embeddings, no vector database, no
network call - which means retrieval is deterministic, runs in a unit test, and
produces the same ranking on every machine. For a corpus of a few hundred short,
heavily jargonised clauses that is not a compromise: exact term overlap is a
strong signal when the query and the corpus share vocabulary, and the terms that
matter here ("final sale", "signature", "window") appear verbatim in both.

Phase 2 adds a dense retriever alongside this one and fuses the rankings. The
lexical half stays, because it is the half that can be reasoned about when a
retrieval goes wrong.

Deliberately absent: any way for the caller to pass a raw filter expression. The
query is text and the filters are a fixed, typed set. A retrieval tool that
accepts arbitrary predicates is a tool an injected instruction can aim.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from backstop_domain.policy import PolicyClause, PolicyCorpus
from backstop_domain.text import fold

# BM25 parameters. k1 controls term-frequency saturation, b controls length
# normalisation. These are the standard defaults; clause length varies little
# here, so the ranking is not sensitive to them.
_K1 = 1.5
_B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+")

#: Words that carry no discriminating power in a policy corpus. Kept short on
#: purpose: an over-eager stop list removes "not", and "not" changes meanings.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "where",
        "which",
        "will",
        "with",
        "within",
    }
)


def tokenize(text: str) -> list[str]:
    """Fold, split on non-alphanumerics, drop stopwords.

    Turkish folding runs first so that a query written with Turkish characters
    matches an English-language corpus term and vice versa.
    """
    return [token for token in _TOKEN.findall(fold(text)) if token not in _STOPWORDS]


@dataclass(frozen=True, slots=True)
class RetrievedClause:
    """One hit, with the score and the terms that earned it."""

    clause: PolicyClause
    score: float
    matched_terms: tuple[str, ...]

    @property
    def clause_id(self) -> str:
        return self.clause.id


class ClauseIndex:
    """BM25 index over a policy corpus.

    Built once and reused. Construction is O(clauses x terms) and takes
    milliseconds for a corpus this size.
    """

    def __init__(self, corpus: PolicyCorpus) -> None:
        self._corpus = corpus
        self._clauses = corpus.clauses

        # Section titles are indexed alongside clause text. A query for "return
        # window" should reach RP-2.1 even though the clause body says "30
        # calendar days" and the heading carries the phrase.
        self._tokens: list[list[str]] = [
            tokenize(f"{clause.section_title} {clause.text}") for clause in self._clauses
        ]
        self._frequencies: list[Counter[str]] = [Counter(tokens) for tokens in self._tokens]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._average_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            document_frequency.update(set(tokens))

        total = len(self._clauses)
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self._clauses)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        document_id: str | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedClause]:
        """Rank clauses against a text query.

        Args:
            query: Free text. Typically the ticket summary plus the intent.
            limit: Maximum hits. Bounded so a tool call cannot flood a context.
            document_id: Restrict to one document. A fixed, typed filter.
            min_score: Drop weak hits. Returning nothing is a valid, useful answer;
                five irrelevant clauses invite a model to cite one of them.

        Returns:
            Hits ordered by score, then by clause id so that ties are stable.
        """
        query_terms = tokenize(query)
        if not query_terms:
            return []

        bounded = max(1, min(limit, 20))
        results: list[RetrievedClause] = []

        for position, clause in enumerate(self._clauses):
            if document_id is not None and clause.document_id != document_id:
                continue

            score = 0.0
            matched: list[str] = []
            frequencies = self._frequencies[position]
            length = self._lengths[position]

            for term in set(query_terms):
                occurrences = frequencies.get(term, 0)
                if occurrences == 0:
                    continue
                matched.append(term)
                idf = self._idf.get(term, 0.0)
                denominator = occurrences + _K1 * (
                    1 - _B + _B * (length / self._average_length if self._average_length else 1)
                )
                score += idf * (occurrences * (_K1 + 1)) / denominator

            if score > min_score:
                results.append(
                    RetrievedClause(
                        clause=clause,
                        score=round(score, 6),
                        matched_terms=tuple(sorted(matched)),
                    )
                )

        results.sort(key=lambda hit: (-hit.score, hit.clause.id))
        return results[:bounded]

    def get(self, clause_id: str) -> PolicyClause | None:
        return self._corpus.get_clause(clause_id)


__all__ = ["ClauseIndex", "RetrievedClause", "tokenize"]
