"""The policy corpus and clause retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from backstop_domain.generator import RETURN_WINDOW_DAYS
from backstop_domain.policy import (
    ExpectedBehaviour,
    PolicyCorpus,
    load_corpus,
    parse_document,
)
from backstop_domain.retrieval import ClauseIndex, tokenize

POLICY_DIR = Path(__file__).resolve().parents[3] / "seed-data" / "policies"


@pytest.fixture(scope="module")
def corpus() -> PolicyCorpus:
    return load_corpus(POLICY_DIR)


@pytest.fixture(scope="module")
def index(corpus: PolicyCorpus) -> ClauseIndex:
    return ClauseIndex(corpus)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_the_three_policies_load(corpus: PolicyCorpus) -> None:
    assert {document.document_id for document in corpus.documents} == {
        "return-policy",
        "delivery-policy",
        "goodwill-policy",
    }


def test_clauses_are_addressable(corpus: PolicyCorpus) -> None:
    clause = corpus.get_clause("RP-5.3")
    assert clause is not None
    assert clause.section_id == "RP-5"
    assert "signature" in clause.text


def test_clause_text_is_prose_not_markdown(corpus: PolicyCorpus) -> None:
    """Clause text reaches a model context and an audit entry. No source markers."""
    assert all("**" not in clause.text for clause in corpus.clauses)
    assert all("*" not in clause.text for clause in corpus.clauses)


def test_a_section_keeps_its_clauses_together(corpus: PolicyCorpus) -> None:
    ids = [clause.id for clause in corpus.get_section("RP-5")]
    assert ids == ["RP-5.1", "RP-5.2", "RP-5.3", "RP-5.4"]


def test_every_document_declares_a_version(corpus: PolicyCorpus) -> None:
    """A decision defended later must name the policy that was in force."""
    for document in corpus.documents:
        assert document.version
        assert document.effective_from


def test_front_matter_is_required() -> None:
    with pytest.raises(ValueError, match="front matter"):
        parse_document("# No front matter\n\n## RP-1 Scope\n\n**RP-1.1** Text.\n")


def test_a_clause_prefix_must_match_its_document() -> None:
    source = (
        "---\ndocument_id: x\ntitle: X\nprefix: RP\nversion: '1'\n"
        "effective_from: 2026-01-01\nowner: Ops\n---\n\n"
        "## RP-1 Scope\n\n**DP-1.1** Wrong prefix.\n"
    )
    with pytest.raises(ValueError, match="does not match the document prefix"):
        parse_document(source)


def test_a_clause_outside_any_section_is_an_error() -> None:
    """Silently dropping it would make the clause uncitable and invisible."""
    source = (
        "---\ndocument_id: x\ntitle: X\nprefix: RP\nversion: '1'\n"
        "effective_from: 2026-01-01\nowner: Ops\n---\n\n"
        "**RP-1.1** Orphan clause.\n"
    )
    with pytest.raises(ValueError, match="before any section heading"):
        parse_document(source)


# ---------------------------------------------------------------------------
# Alignment with the code
# ---------------------------------------------------------------------------


def test_the_stated_return_window_matches_the_generator(corpus: PolicyCorpus) -> None:
    """RP-2.1 and RETURN_WINDOW_DAYS must not drift apart.

    The generator plants wardrobing returns "just inside the window" and the
    catalogue tool reports whether an item is within it. If the prose said 30 days
    and the code said 14, every one of those would be quietly wrong.
    """
    clause = corpus.get_clause("RP-2.1")
    assert clause is not None
    assert f"{RETURN_WINDOW_DAYS} calendar days" in clause.text


# ---------------------------------------------------------------------------
# Ambiguities
# ---------------------------------------------------------------------------


def test_the_planted_ambiguities_load(corpus: PolicyCorpus) -> None:
    assert len(corpus.ambiguities) >= 6


def test_every_ambiguity_cites_clauses_that_exist(corpus: PolicyCorpus) -> None:
    """Enforced on load; asserted here so the reason is visible."""
    known = {clause.id for clause in corpus.clauses}
    for ambiguity in corpus.ambiguities:
        assert set(ambiguity.clauses) <= known, ambiguity.id


def test_an_ambiguity_spans_at_least_two_clauses(corpus: PolicyCorpus) -> None:
    """One clause cannot contradict itself; a conflict needs two."""
    assert all(len(ambiguity.clauses) >= 2 for ambiguity in corpus.ambiguities)


def test_the_expected_behaviours_cover_all_three_routes(corpus: PolicyCorpus) -> None:
    """Deliberate, escalate and let policy-as-code bind: all three are exercised."""
    behaviours = {ambiguity.expected_behaviour for ambiguity in corpus.ambiguities}
    assert behaviours == set(ExpectedBehaviour)


def test_discretion_without_a_ceiling_is_bound_by_code(corpus: PolicyCorpus) -> None:
    """AMB-04 is the case for policy-as-code, not for a debate."""
    amb = next(item for item in corpus.ambiguities if item.id == "AMB-04")
    assert amb.expected_behaviour is ExpectedBehaviour.POLICY_ENGINE_BINDS
    assert "GP-3.3" in amb.clauses


def test_each_ambiguity_records_the_plausible_wrong_answers(corpus: PolicyCorpus) -> None:
    assert all(ambiguity.must_not for ambiguity in corpus.ambiguities)


def test_clauses_can_be_traced_back_to_their_ambiguities(corpus: PolicyCorpus) -> None:
    assert {item.id for item in corpus.ambiguities_for("RP-4.2")} == {"AMB-01"}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_tokenizing_folds_and_drops_stopwords() -> None:
    assert tokenize("The İtem is Damaged") == ["item", "damaged"]


def test_not_survives_tokenization() -> None:
    """An over-eager stop list removes "not", and "not" changes meanings."""
    assert "not" in tokenize("the item was not delivered")


def test_delivery_evidence_query_finds_the_evidence_clauses(index: ClauseIndex) -> None:
    hits = index.search("parcel never arrived but courier recorded a signature", limit=3)
    assert "DP-3.2" in {hit.clause_id for hit in hits}


def test_late_delivery_query_finds_the_lateness_clauses(index: ClauseIndex) -> None:
    hits = index.search("delivery was four days late and I missed the occasion", limit=3)
    ids = {hit.clause_id for hit in hits}
    assert ids & {"DP-2.2", "DP-6.1", "DP-6.2"}


def test_results_are_ordered_by_score(index: ClauseIndex) -> None:
    hits = index.search("refund store credit goodwill", limit=6)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_ties_break_deterministically(index: ClauseIndex) -> None:
    """Two runs must rank identically, or eval scores are not comparable."""
    first = [hit.clause_id for hit in index.search("return", limit=8)]
    second = [hit.clause_id for hit in index.search("return", limit=8)]
    assert first == second


def test_a_document_filter_restricts_results(index: ClauseIndex) -> None:
    hits = index.search("refund", limit=8, document_id="goodwill-policy")
    assert hits
    assert all(hit.clause.document_id == "goodwill-policy" for hit in hits)


def test_a_query_of_only_stopwords_returns_nothing(index: ClauseIndex) -> None:
    """Returning nothing is a useful answer. It should push the caller to escalate."""
    assert index.search("the and of to") == []


def test_the_result_limit_is_capped(index: ClauseIndex) -> None:
    assert len(index.search("return refund delivery", limit=500)) <= 20


def test_hits_report_which_terms_matched(index: ClauseIndex) -> None:
    """Needed for groundedness checking: a citation must be explainable."""
    hits = index.search("hygiene sensitive cosmetics", limit=3)
    assert hits
    assert all(hit.matched_terms for hit in hits)


def test_lexical_retrieval_misses_pure_paraphrase(index: ClauseIndex) -> None:
    """A recorded limitation, not an accident.

    "Money back" shares no term with "full refund", so the clause that grants the
    entitlement - RP-4.1 - does not surface for a customer who phrases it that
    way. This is the gap the dense retriever closes in Phase 2. It is asserted so
    that the day fusion lands, this test fails and someone updates the claim.
    """
    hits = index.search("item arrived broken, want my money back", limit=5)
    ids = {hit.clause_id for hit in hits}
    assert "RP-4.1" not in ids
