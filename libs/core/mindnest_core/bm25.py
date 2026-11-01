"""Okapi BM25 ranking over Postgres full-text vectors.

Postgres ranks full-text matches with ts_rank / ts_rank_cd, which are not BM25: they have no
inverse-document-frequency term and no document-length normalisation. This module adds both,
using the numbers Postgres already stores in the chunk's `tsv` column, so no extension and no
second index are needed.

What a tsvector holds, as text:    'photosynthesis':4,17 'light':9 'the':1,12
  * each distinct lexeme (the word after the 'simple' tokenizer: lower-cased, nothing removed);
  * the positions where it occurs. The number of positions is the term frequency (tf), and the
    sum over all lexemes is the document length (dl) in tokens.

BM25 score of a document d for a query q:
    sum over query terms t of  idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
    idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5))        (never negative, as in Lucene)

Everything here is pure: the SQL that supplies N, avgdl and df lives in retrieval.py.
"""

import math
import re
from collections.abc import Iterable, Sequence
from typing import TypeVar

BM25_K1 = 1.2
BM25_B = 0.75

K = TypeVar("K")

# 'lexeme' or 'lexeme':1,2,3A  (a quote inside a lexeme is doubled, a backslash is escaped).
_ENTRY = re.compile(r"'((?:[^']|'')*)'(?::([0-9A-Da-d,]+))?")
_ESCAPE = re.compile(r"\\(.)")


def parse_tsvector(value: str) -> dict[str, int]:
    """Lexeme -> number of occurrences, read from a tsvector's text form.

    A lexeme stored without positions (a stripped vector) counts once."""
    counts: dict[str, int] = {}
    for match in _ENTRY.finditer(value):
        lexeme = _ESCAPE.sub(r"\1", match.group(1).replace("''", "'"))
        positions = match.group(2)
        counts[lexeme] = counts.get(lexeme, 0) + (positions.count(",") + 1 if positions else 1)
    return counts


def query_terms(value: str) -> list[str]:
    """The distinct lexemes of a query, in order, read from `to_tsvector(...)::text`."""
    return sorted(parse_tsvector(value))


def idf(n_docs: int, doc_freq: int) -> float:
    """Inverse document frequency; rare terms weigh more, and the value is always positive."""
    return math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))


def score_document(
    terms: Iterable[str],
    counts: dict[str, int],
    *,
    idfs: dict[str, float],
    avg_len: float,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> float:
    """BM25 score of one document (its lexeme counts) for the query terms."""
    length = sum(counts.values())
    norm = 1.0 - b + b * (length / avg_len if avg_len > 0 else 1.0)
    total = 0.0
    for term in terms:
        tf = counts.get(term, 0)
        if tf:
            total += idfs.get(term, 0.0) * tf * (k1 + 1.0) / (tf + k1 * norm)
    return total


def rank(
    terms: Sequence[str],
    documents: Sequence[tuple[K, str]],
    *,
    n_docs: int,
    avg_len: float,
    doc_freq: dict[str, int],
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> list[tuple[K, float]]:
    """Score documents given as (key, tsvector text) and return (key, score), best first.

    `n_docs`, `avg_len` and `doc_freq` describe the whole searched collection, not just the
    documents passed in, so a term that is common everywhere stays cheap even if only a few
    candidates are being ranked. A term's document frequency is raised to the number of passed
    documents that contain it if the collection figure is lower (the two should agree).
    Ties keep the order the documents arrived in."""
    parsed = [(key, parse_tsvector(vector)) for key, vector in documents]
    unique = list(dict.fromkeys(terms))
    idfs: dict[str, float] = {}
    for term in unique:
        seen = sum(1 for _, counts in parsed if term in counts)
        idfs[term] = idf(n_docs, max(doc_freq.get(term, 0), seen))
    scored = [
        (key, score_document(unique, counts, idfs=idfs, avg_len=avg_len, k1=k1, b=b))
        for key, counts in parsed
    ]
    return sorted(scored, key=lambda item: item[1], reverse=True)


# A word found in more than this share of the chunks says little about what a question is
# about ("what", "is", "the"). It is left out when choosing which chunks to score, but still
# counts in the score itself (with a very low idf).
COMMON_TERM_RATIO = 0.5


def pool_terms(
    terms: Sequence[str],
    doc_freq: dict[str, int],
    n_docs: int,
    max_ratio: float = COMMON_TERM_RATIO,
) -> list[str]:
    """The query words that decide which chunks are worth scoring.

    Words that appear nowhere are dropped; so are words that appear in more than `max_ratio`
    of the chunks, unless nothing else is left (a question made only of common words)."""
    present = [term for term in dict.fromkeys(terms) if doc_freq.get(term, 0) > 0]
    selective = [term for term in present if doc_freq[term] <= max_ratio * n_docs]
    return selective or present
