"""Scoring, dataset parsing and redaction. Pure functions: no database needed."""

import io
import json
import logging

from mindnest_core.evaldata import canary_of, parse_dataset
from mindnest_core.evalmetrics import (
    CaseRow,
    Evidence,
    PassageView,
    cited_numbers,
    citation_scores,
    matches_evidence,
    normalize_for_match,
    parse_evidence,
    parse_judge,
    percentile,
    relevance_flags,
    retrieval_scores,
    summarize,
)
from mindnest_core.redact import REDACTED, RedactingFilter, redact


def view(text: str, filename: str = "notes.pdf") -> PassageView:
    return PassageView(filename=filename, text=text)


# ------------------------------------------------------------------ matching


def test_normalizing_ignores_case_spacing_punctuation_and_soft_hyphens():
    assert normalize_for_match("Photo-\nsynthesis,  Occurs!") == normalize_for_match("photosynthesis occurs")
    assert normalize_for_match("a­b​c") == "abc"


def test_hindi_and_gujarati_survive_normalizing():
    hindi = normalize_for_match("प्रकाश संश्लेषण।")
    assert hindi == normalize_for_match("प्रकाश\nसंश्लेषण")
    assert len(hindi) > 5  # vowel signs and viraama are kept, so words stay distinct
    assert normalize_for_match("ગુજરાત હાઈકોર્ટ") == normalize_for_match("ગુજરાત  હાઈકોર્ટ.")
    assert normalize_for_match("क") != normalize_for_match("ख")


def test_evidence_matches_on_phrase_and_optionally_file():
    passage = view("The Calvin cycle fixes carbon dioxide.", "Biology Notes.pdf")
    assert matches_evidence(passage, Evidence("calvin  cycle fixes"))
    assert matches_evidence(passage, Evidence("calvin cycle", file="biology notes"))
    assert not matches_evidence(passage, Evidence("calvin cycle", file="chemistry.pdf"))
    assert not matches_evidence(passage, Evidence("krebs cycle"))
    assert not matches_evidence(passage, Evidence("   "))


def test_evidence_can_list_alternative_wordings():
    evidence = Evidence("end-to-end completion ~36% || chain 20 steps at 95% per-step success", file="harness")
    summary = PassageView("harness.pdf", "A 20-step pipeline ... chain 20 steps at 95% per-step success and it drops.")
    table = PassageView("harness.pdf", "Fact: end-to-end completion ~36% Tool-call failure rate")
    other = PassageView("harness.pdf", "Nothing about it here.")
    assert matches_evidence(summary, evidence) and matches_evidence(table, evidence)
    assert not matches_evidence(other, evidence)
    # An empty alternative (a stray "||") must not match everything.
    assert not matches_evidence(other, Evidence("real words||"))


def test_parse_evidence_ignores_unusable_entries():
    items = parse_evidence(
        ["plain phrase", {"phrase": "with file", "file": "a.pdf", "page": 3}, {"phrase": ""}, 5, {"page": 1}]
    )
    assert [e.phrase for e in items] == ["plain phrase", "with file"]
    assert items[1].file == "a.pdf" and items[1].page == 3
    assert parse_evidence(None) == []


# ------------------------------------------------------------------ retrieval


def test_retrieval_scores_for_two_pieces_of_evidence():
    passages = [view("unrelated text"), view("alpha fact is here"), view("beta fact is here")]
    evidence = [Evidence("alpha fact"), Evidence("beta fact")]
    scores = retrieval_scores(passages, evidence)
    assert scores["recall_at_1"] == 0.0
    assert scores["recall_at_3"] == 1.0
    assert scores["recall_at_k"] == 1.0
    assert scores["mrr"] == 0.5
    assert scores["hit_at_k"] == 1.0
    assert abs(scores["precision_at_k"] - 2 / 3) < 1e-9


def test_recall_looks_deeper_than_k_but_k_metrics_stop_at_k():
    passages = [view(f"filler {n}") for n in range(1, 8)] + [view("the needle fact"), view("x"), view("y")]
    evidence = [Evidence("needle fact")]  # the 8th passage
    scores = retrieval_scores(passages, evidence, k=6)
    assert scores["recall_at_1"] == scores["recall_at_3"] == scores["recall_at_5"] == 0.0
    assert scores["recall_at_10"] == 1.0  # found by depth 10, even though K is 6
    assert scores["recall_at_k"] == 0.0 and scores["hit_at_k"] == 0.0 and scores["mrr"] == 0.0
    assert scores["precision_at_k"] == 0.0
    wide = retrieval_scores(passages, evidence, k=10)
    assert wide["recall_at_k"] == 1.0 and wide["mrr"] == 1 / 8


def test_recall_at_5_counts_the_fifth_passage_but_not_the_sixth():
    base = [view("filler")] * 4
    fifth = retrieval_scores([*base, view("needle")], [Evidence("needle")], k=6)
    sixth = retrieval_scores([*base, view("filler"), view("needle")], [Evidence("needle")], k=6)
    assert fifth["recall_at_5"] == 1.0 and sixth["recall_at_5"] == 0.0
    assert sixth["recall_at_10"] == 1.0 and sixth["recall_at_k"] == 1.0


def test_retrieval_scores_when_nothing_matches_or_nothing_was_found():
    assert retrieval_scores([view("x")], [Evidence("needle")])["mrr"] == 0.0
    empty = retrieval_scores([], [Evidence("needle")])
    assert empty["recall_at_k"] == 0.0 and empty["precision_at_k"] == 0.0
    assert retrieval_scores([view("x")], []) == {}


def test_relevance_flags_follow_rank_order():
    flags = relevance_flags([view("a"), view("needle here"), view("b")], [Evidence("needle")])
    assert flags == [False, True, False]


# ------------------------------------------------------------------ citations


def test_cited_numbers_understands_common_shapes():
    assert cited_numbers("Yes [1]. Also [2][3] and [1, 4].") == [1, 2, 3, 4]
    assert cited_numbers("no citations, only [a] and (1)") == []


def test_citation_scores_flag_invented_and_irrelevant_sources():
    relevant = [True, False, True]
    good = citation_scores("Fact [1] and [3].", relevant)
    assert good == {"cited_any": 1.0, "citation_validity": 1.0, "citation_accuracy": 1.0}
    mixed = citation_scores("Fact [1] and [2] and [9].", relevant)
    validity = mixed["citation_validity"]
    assert validity is not None and abs(validity - 2 / 3) < 1e-9
    assert mixed["citation_accuracy"] == 0.5  # [1] is relevant, [2] is not, [9] does not exist
    none = citation_scores("No sources used.", relevant)
    assert none["cited_any"] == 0.0 and none["citation_validity"] is None


# ------------------------------------------------------------------ the judge


def test_parse_judge_reads_plain_and_fenced_json():
    plain = parse_judge('{"correctness": 4, "faithfulness": 5, "relevance": 3, "abstained": false}')
    assert plain == {"correctness": 0.8, "faithfulness": 1.0, "relevance": 0.6, "abstained": False}
    fenced = parse_judge('Sure!\n```json\n{"correctness": 0, "faithfulness": 2.5, "relevance": 9, "abstained": true}\n```')
    assert fenced is not None
    assert fenced["faithfulness"] == 0.5 and fenced["relevance"] == 1.0  # clamped to 0..5
    assert fenced["abstained"] is True


def test_parse_judge_rejects_unusable_replies():
    assert parse_judge("I would say it is good.") is None
    assert parse_judge('{"correctness": 4}') is None
    assert parse_judge('{"correctness": "high", "faithfulness": 1, "relevance": 1}') is None


# ------------------------------------------------------------------ summaries


def test_percentile_is_nearest_rank():
    assert percentile([4, 1, 3, 2], 50) == 2
    assert percentile([4, 1, 3, 2], 95) == 4
    assert percentile([], 50) is None


def test_summarize_averages_per_language_and_counts_problems():
    rows = [
        CaseRow("en", True, {"mrr": 1.0, "recall_at_k": 1.0}, {"retrieval_ms": 10}),
        CaseRow("en", True, {"mrr": 0.5, "recall_at_k": 1.0}, {"retrieval_ms": 30, "degraded": 1}),
        CaseRow("hi", True, {"mrr": 0.0, "recall_at_k": 0.0}, {"retrieval_ms": 20}),
        CaseRow("gu", False, {"abstain": 1.0}, {}, failed=True),
    ]
    summary = summarize(rows)
    assert summary["cases"] == 4 and summary["failed"] == 1 and summary["degraded"] == 1
    assert summary["answerable"] == 3 and summary["unanswerable"] == 1
    assert summary["metrics"]["mrr"] == 0.5
    assert summary["metrics"]["abstain"] == 1.0
    assert summary["by_language"]["en"]["metrics"]["mrr"] == 0.75
    assert summary["by_language"]["hi"]["cases"] == 1
    assert summary["latency"]["retrieval_ms_p50"] == 20


# ------------------------------------------------------------------ dataset files


def line(**overrides):
    base = {
        "id": "en-01", "language": "en", "question": "What is photosynthesis?",
        "reference_answer": "Plants turn light into sugar.", "answerable": True,
        "evidence": [{"file": "bio.pdf", "phrase": "light into chemical"}], "tags": ["factual"],
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def test_a_valid_dataset_is_parsed():
    unanswerable = line(id="en-02", answerable=False, reference_answer=None, evidence=[])
    cases, errors = parse_dataset(f"{line()}\n\n{unanswerable}\n")
    assert errors == []
    assert [c.key for c in cases] == ["en-01", "en-02"]
    assert cases[0].evidence == [{"phrase": "light into chemical", "file": "bio.pdf"}]
    assert cases[1].answerable is False


def test_problems_are_reported_with_line_numbers():
    content = "\n".join(
        [
            "not json",
            line(id="bad id!"),
            line(language="fr"),
            line(evidence=[]),
            line(reference_answer=""),
            line(),
            line(),
        ]
    )
    _, errors = parse_dataset(content)
    assert errors[0] == "line 1: not valid JSON"
    assert any(e.startswith("line 2:") and '"id"' in e for e in errors)
    assert any(e.startswith("line 3:") and "language" in e for e in errors)
    assert any(e.startswith("line 4:") and "evidence" in e for e in errors)
    assert any(e.startswith("line 5:") and "reference_answer" in e for e in errors)
    assert any(e.startswith("line 7:") and "duplicate" in e for e in errors)


def test_an_empty_file_is_an_error():
    assert parse_dataset("\n\n")[1] == ["the file has no questions"]


def test_canary_tag():
    assert canary_of(["injection", "canary:PWNED-7731"]) == "PWNED-7731"
    assert canary_of(["factual"]) is None


# ------------------------------------------------------------------ redaction


def test_exact_keys_and_key_shapes_are_removed():
    key = "my-custom-provider-secret"
    text = (
        f"failed with {key}; sk-ant-api03-ABCDEFGHIJKL; sk-proj-abcdefghijklmnop1234; "
        "AIzaSyA1234567890abcdefghijklmnopq; gsk_abcdefghijklmnop1234; Authorization: Bearer abcdefghijklmnopqrstuvwx"
    )
    cleaned = redact(text, [key])
    for secret in (key, "ABCDEFGHIJKL", "abcdefghijklmnop1234", "AIzaSyA1234567890", "gsk_abcdef", "abcdefghijklmnopqrstuvwx"):
        assert secret not in cleaned
    assert REDACTED in cleaned
    assert "Bearer" in cleaned  # the word stays; only the token goes


def test_ordinary_text_is_untouched():
    text = "Photosynthesis occurs in chloroplasts [1]. Ask-me-anything."
    assert redact(text) == text


def test_logging_filter_scrubs_messages_and_arguments():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("mindnest.test_redact")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.error("call failed for key %s", "sk-test-1234567890abcdef")
        try:
            raise RuntimeError("401 for sk-test-1234567890abcdef")
        except RuntimeError:
            logger.exception("again")
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "sk-test-1234567890abcdef" not in output
    assert REDACTED in output
