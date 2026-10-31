"""Checks on quiz questions written by an AI, made before a question is saved or shown.

An AI can return a question whose answer key does not match its options, two options that say
the same thing, a question that is already in the quiz, or a one-word "question". None of that may
reach a student, so every question goes through `check_question` and a `QuestionChecker` (which
also remembers what the quiz already asks). A question that fails is discarded and counted; it is
never repaired by guessing, and nothing here invents content.

Pure functions and small classes: no database, no network.
"""

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

QTYPES = ("mcq", "true_false", "short")

PROMPT_MIN = 8
PROMPT_MAX = 500
MCQ_OPTIONS = 4  # the number of choices every generated multiple-choice question has
MIN_OPTIONS = 3  # fewer than this is reported as "too few" rather than "wrong number"
OPTION_MAX = 250
ANSWER_MIN = 2
ANSWER_MAX = 600


def normalise_text(value: str) -> str:
    """Text reduced for comparison: Unicode-normalised, case-folded, punctuation removed and
    whitespace collapsed. Letters and combining marks are kept, so Hindi and Gujarati words
    compare correctly ("Chlorophyll?" equals "chlorophyll", "प्रकाश।" equals "प्रकाश").
    """
    folded = unicodedata.normalize("NFKC", str(value)).casefold()
    kept: list[str] = []
    for ch in folded:
        category = unicodedata.category(ch)
        if category == "Cf":  # zero-width joiners and similar: invisible, so drop them
            continue
        kept.append(" " if category[0] in "PSZC" else ch)
    return " ".join("".join(kept).split())


# Choices that point at other choices cannot be marked reliably: "all of the above" is right or
# wrong depending on which other option is the key, and a student can defend several answers.
_META_OPTIONS = frozenset(
    normalise_text(text)
    for text in (
        "all of the above", "all the above", "all of these", "all of them", "none of the above",
        "none of these", "none of them", "both of the above", "both a and b", "both b and c",
        "a and b", "b and c", "a and c", "all are correct", "all are true", "none is correct",
        "उपरोक्त सभी", "ऊपर के सभी", "इनमें से कोई नहीं", "उपरोक्त में से कोई नहीं", "सभी सही हैं",
        "ઉપરોક્ત બધા", "ઉપરના બધા", "આમાંથી એક પણ નહીં", "ઉપરોક્તમાંથી એક પણ નહીં", "બધા સાચા છે",
    )
)


@dataclass(frozen=True)
class Candidate:
    """One question as an AI wrote it, before it is saved. For multiple choice `answer` is the
    0-based index of the right option written as text; for true/false it is "true" or "false";
    for a short answer it is the model answer."""

    qtype: str
    prompt: str
    options: Sequence[str] | None = None
    answer: str = ""
    source: Mapping[str, Any] | None = None


# ------------------------------------------------------------------------------ one question


def check_source(source: Mapping[str, Any] | None) -> list[str]:
    """A question made from the student's materials must point at the passage it came from."""
    if not isinstance(source, Mapping) or not source:
        return ["no_source"]
    filename = source.get("filename")
    snippet = source.get("text")
    if not (isinstance(filename, str) and filename.strip() and isinstance(snippet, str) and snippet.strip()):
        return ["source_incomplete"]
    return []


def _check_choices(options: Sequence[Any] | None, answer: str) -> list[str]:
    issues: list[str] = []
    if options is None or isinstance(options, (str, bytes)):
        return ["options_missing"]
    cleaned = [o.strip() if isinstance(o, str) else "" for o in options]
    if len(cleaned) < MIN_OPTIONS:
        issues.append("too_few_options")
    elif len(cleaned) != MCQ_OPTIONS:
        issues.append("option_count")
    if any(not o for o in cleaned):
        issues.append("option_empty")
    if any(len(o) > OPTION_MAX for o in cleaned):
        issues.append("option_too_long")
    normal = [normalise_text(o) for o in cleaned if o]
    if len(set(normal)) != len(normal):
        issues.append("duplicate_options")
    if any(n in _META_OPTIONS for n in normal):
        issues.append("ambiguous_option")

    key = answer.strip()
    if not key:
        issues.append("answer_missing")
    elif not (key.isascii() and key.isdigit()) or key != str(int(key)):
        issues.append("answer_invalid")  # not a plain index such as "2"
    elif int(key) >= len(cleaned) or not cleaned[int(key)]:
        issues.append("answer_not_in_options")
    return issues


def check_question(candidate: Candidate, *, require_source: bool = False) -> list[str]:
    """Every problem found with one question, as stable codes; an empty list means it is fine.

    `require_source` is set for questions made from the student's materials, which must carry a
    reference to their passage; a general-knowledge quiz has none and says so everywhere.
    """
    if candidate.qtype not in QTYPES:
        return ["bad_type"]
    issues: list[str] = []
    prompt = candidate.prompt.strip()
    if len(prompt) < PROMPT_MIN:
        issues.append("prompt_too_short")
    elif len(prompt) > PROMPT_MAX:
        issues.append("prompt_too_long")

    if candidate.qtype == "mcq":
        issues += _check_choices(candidate.options, candidate.answer)
    else:
        if candidate.options:
            issues.append("unexpected_options")
        answer = candidate.answer.strip()
        if candidate.qtype == "true_false":
            if answer not in ("true", "false"):
                issues.append("answer_invalid")
        elif not answer:
            issues.append("answer_missing")
        elif len(answer) < ANSWER_MIN:
            issues.append("answer_too_short")
        elif len(answer) > ANSWER_MAX:
            issues.append("answer_too_long")

    if require_source:
        issues += check_source(candidate.source)
    return issues


def primary_issue(issues: Sequence[str]) -> str:
    """The reason a rejected question is filed under (the first problem found)."""
    return issues[0] if issues else "malformed"


# ------------------------------------------------------------------------------ a whole quiz


def find_duplicates(prompts: Iterable[str]) -> list[int]:
    """Positions of questions that repeat an earlier one once punctuation, case and spacing are
    ignored. The first occurrence is kept."""
    seen: set[str] = set()
    repeated: list[int] = []
    for position, prompt in enumerate(prompts):
        key = normalise_text(prompt)
        if key and key in seen:
            repeated.append(position)
        else:
            seen.add(key)
    return repeated


class QuestionChecker:
    """Checks questions one by one against everything the quiz already asks.

    `existing` holds questions already in the quiz (or an earlier round of writing it). A question
    is only remembered once it has been admitted, so a rejected one can be asked again later.
    """

    def __init__(self, existing: Iterable[str] = ()) -> None:
        self._seen = {normalise_text(p) for p in existing}

    def check(self, candidate: Candidate, *, require_source: bool = False) -> list[str]:
        issues = check_question(candidate, require_source=require_source)
        key = normalise_text(candidate.prompt)
        if key and key in self._seen:
            issues.append("duplicate_question")
        return issues

    def admit(self, candidate: Candidate, *, require_source: bool = False) -> list[str]:
        """Like `check`, and when nothing is wrong the question is remembered as asked."""
        issues = self.check(candidate, require_source=require_source)
        if not issues:
            self._seen.add(normalise_text(candidate.prompt))
        return issues

    def forget(self, prompt: str) -> None:
        """Take back an admitted question that was rejected for a later reason."""
        self._seen.discard(normalise_text(prompt))

    def __len__(self) -> int:
        return len(self._seen)


@dataclass
class RejectionLog:
    """How many questions were discarded while writing a quiz, and why (one reason each)."""

    reasons: Counter[str] = field(default_factory=Counter)

    def add(self, reason: str) -> None:
        self.reasons[reason] += 1

    def extend(self, reasons: Iterable[str]) -> None:
        self.reasons.update(reasons)

    @property
    def total(self) -> int:
        return sum(self.reasons.values())

    def as_dict(self) -> dict[str, int]:
        """Reason -> count, the most common first."""
        return dict(self.reasons.most_common())
