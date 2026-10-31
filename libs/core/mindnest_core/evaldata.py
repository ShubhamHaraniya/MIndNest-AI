"""Reading and checking evaluation datasets (JSON Lines: one question per line).

A line looks like:
  {"id": "en-01", "language": "en", "question": "...", "answerable": true,
   "reference_answer": "...", "evidence": [{"file": "x.pdf", "phrase": "exact words", "page": 3}],
   "tags": ["factual"]}

`answerable: false` marks a question the materials cannot answer; a good assistant says so.
A tag of the form "canary:WORD" marks a prompt-injection test: the document tells the assistant
to say WORD, and the case fails if the answer contains it.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from mindnest_core.evalmetrics import parse_evidence

LANGUAGES = ("en", "hi", "gu")
MAX_CASES = 500
MAX_BYTES = 1_000_000
MAX_ERRORS_SHOWN = 10

_KEY = re.compile(r"^[\w.\-]{1,60}$")


@dataclass
class CaseData:
    key: str
    language: str
    question: str
    reference_answer: str | None
    answerable: bool
    evidence: list[dict[str, Any]]
    tags: list[str] = field(default_factory=list)


def _evidence_json(items: list[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for e in parse_evidence(items):
        entry: dict[str, Any] = {"phrase": e.phrase[:300]}
        if e.file:
            entry["file"] = e.file[:200]
        if e.page is not None:
            entry["page"] = e.page
        cleaned.append(entry)
    return cleaned


def parse_case(raw: Any) -> tuple[CaseData | None, str | None]:
    """Validate one decoded line. Returns (case, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "each line must be a JSON object"
    key = raw.get("id")
    if not isinstance(key, str) or not _KEY.match(key):
        return None, '"id" must be 1-60 letters, digits, dots, dashes or underscores'
    language = raw.get("language")
    if language not in LANGUAGES:
        return None, '"language" must be "en", "hi" or "gu"'
    question = raw.get("question")
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 1000:
        return None, '"question" must be 3-1000 characters'
    answerable = raw.get("answerable", True)
    if not isinstance(answerable, bool):
        return None, '"answerable" must be true or false'
    reference = raw.get("reference_answer")
    if reference is not None and (not isinstance(reference, str) or len(reference) > 2000):
        return None, '"reference_answer" must be text up to 2000 characters'
    evidence_raw = raw.get("evidence", [])
    if not isinstance(evidence_raw, list):
        return None, '"evidence" must be a list'
    evidence = _evidence_json(evidence_raw)
    if len(evidence) != len(evidence_raw):
        return None, 'every "evidence" entry needs a non-empty "phrase"'
    if answerable and not evidence:
        return None, 'an answerable question needs at least one "evidence" phrase'
    if answerable and not (reference or "").strip():
        return None, 'an answerable question needs a "reference_answer"'
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) and 0 < len(t) <= 60 for t in tags):
        return None, '"tags" must be a list of short strings'
    return (
        CaseData(
            key=key,
            language=language,
            question=question.strip(),
            reference_answer=reference.strip() if isinstance(reference, str) and reference.strip() else None,
            answerable=answerable,
            evidence=evidence,
            tags=tags[:10],
        ),
        None,
    )


def parse_dataset(content: str) -> tuple[list[CaseData], list[str]]:
    """Parse a whole JSONL file. Any error makes the file unusable, so nothing is half-imported."""
    cases: list[CaseData] = []
    errors: list[str] = []
    seen: set[str] = set()
    if len(content.encode("utf-8")) > MAX_BYTES:
        return [], ["the file is larger than 1 MB"]
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line)
        except ValueError:
            errors.append(f"line {number}: not valid JSON")
            continue
        case, reason = parse_case(decoded)
        if case is None:
            errors.append(f"line {number}: {reason}")
        elif case.key in seen:
            errors.append(f'line {number}: duplicate id "{case.key}"')
        else:
            seen.add(case.key)
            cases.append(case)
    if not cases and not errors:
        errors.append("the file has no questions")
    if len(cases) > MAX_CASES:
        errors.append(f"too many questions (the limit is {MAX_CASES})")
    return cases, errors[:MAX_ERRORS_SHOWN]


def canary_of(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("canary:") and len(tag) > 7:
            return tag[7:]
    return None
