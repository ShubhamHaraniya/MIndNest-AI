import math

import pytest

from mindnest_core.bm25 import (
    idf,
    parse_tsvector,
    pool_terms,
    query_terms,
    rank,
    score_document,
)


def test_parse_counts_positions():
    assert parse_tsvector("'a':1,5 'b':3 'it''s':2") == {"a": 2, "b": 1, "it's": 1}


def test_parse_lexeme_without_positions_counts_once():
    assert parse_tsvector("'x' 'y'") == {"x": 1, "y": 1}


def test_parse_ignores_weight_letters_and_handles_backslash():
    assert parse_tsvector("'a':1A,2B") == {"a": 2}
    assert parse_tsvector(r"'a\\b':1") == {"a\\b": 1}


def test_parse_hindi_and_gujarati_lexemes():
    assert parse_tsvector("'प्रकाश':1,4 'સંશ્લેષણ':2") == {"प्रकाश": 2, "સંશ્લેષણ": 1}


def test_parse_empty():
    assert parse_tsvector("") == {}


def test_query_terms_are_distinct_and_sorted():
    assert query_terms("'what':1 'is':2 'light':3") == ["is", "light", "what"]


def test_idf_matches_the_formula_and_is_never_negative():
    assert idf(10, 1) == pytest.approx(math.log(1 + 9.5 / 1.5))
    assert idf(10, 10) > 0
    assert idf(10, 1) > idf(10, 5) > idf(10, 10)


def test_single_term_single_document_equals_idf():
    # With tf = 1 and a document as long as the average, the tf and length factors both equal 1.
    idfs = {"a": idf(1, 1)}
    score = score_document(["a"], {"a": 1}, idfs=idfs, avg_len=1.0)
    assert score == pytest.approx(idfs["a"])


def test_rare_term_beats_common_term():
    ranked = rank(
        ["rare", "common"],
        [("has_rare", "'rare':1 'x':2"), ("has_common", "'common':1 'x':2")],
        n_docs=100,
        avg_len=2.0,
        doc_freq={"rare": 2, "common": 90},
    )
    assert [key for key, _ in ranked] == ["has_rare", "has_common"]
    assert ranked[0][1] > ranked[1][1]


def test_shorter_document_wins_with_same_term_frequency():
    ranked = rank(
        ["term"],
        [
            ("long", "'term':1 'x':2,3,4,5,6,7,8,9,10,11"),
            ("short", "'term':1 'x':2"),
        ],
        n_docs=10,
        avg_len=6.0,
        doc_freq={"term": 2},
    )
    assert [key for key, _ in ranked] == ["short", "long"]


def test_term_frequency_saturates():
    def one(tf: int) -> float:
        positions = ",".join(str(i) for i in range(1, tf + 1))
        (_, score), = rank(["t"], [("d", f"'t':{positions}")], n_docs=10, avg_len=float(tf), doc_freq={"t": 1})
        return score

    assert one(20) > one(10) > one(1)
    assert one(20) < 2 * one(10)


def test_ties_keep_arrival_order():
    ranked = rank(
        ["a"],
        [("first", "'a':1"), ("second", "'a':1"), ("third", "'a':1")],
        n_docs=5,
        avg_len=1.0,
        doc_freq={"a": 3},
    )
    assert [key for key, _ in ranked] == ["first", "second", "third"]


def test_documents_without_any_query_term_score_zero():
    ranked = rank(["a"], [("d", "'b':1")], n_docs=5, avg_len=1.0, doc_freq={"a": 1})
    assert ranked == [("d", 0.0)]


def test_zero_average_length_does_not_crash():
    assert rank(["a"], [("d", "'a':1")], n_docs=1, avg_len=0.0, doc_freq={"a": 1})[0][1] > 0


def test_document_frequency_is_raised_to_what_the_candidates_show():
    # The collection says "a" is in 0 chunks, yet two candidates contain it: trust the candidates.
    ranked = rank(["a"], [("d1", "'a':1"), ("d2", "'a':1")], n_docs=10, avg_len=1.0, doc_freq={})
    assert ranked[0][1] == pytest.approx(idf(10, 2) * 1.0, rel=1e-6)


def test_pool_terms_drops_missing_and_very_common_words():
    freq = {"light": 2, "the": 9, "zzz": 0}
    assert pool_terms(["the", "light", "zzz"], freq, 10) == ["light"]


def test_pool_terms_keeps_common_words_when_nothing_else_is_left():
    assert pool_terms(["the", "is"], {"the": 9, "is": 8}, 10) == ["the", "is"]


def test_pool_terms_empty_when_nothing_matches():
    assert pool_terms(["zzz"], {}, 10) == []
