"""Offline check of an evaluation dataset against the documents it was written for.

Reads each document the way the worker does (same parser, same chunk size), then confirms that
every evidence phrase is found inside one passage of the named file. Run it before importing a
dataset, and again whenever a document or question changes. It needs no database, key or model.

    python evals/verify_dataset.py
    python evals/verify_dataset.py --dataset evals/datasets/rag_v2.jsonl --corpus evals/corpus

Run it with the same Python environment as the worker (it uses the worker's own parser).
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from mindnest_core.evaldata import parse_dataset
from mindnest_core.evalmetrics import (
    ALTERNATIVE_SEPARATOR,
    Evidence,
    PassageView,
    matches_evidence,
    parse_evidence,
)
from mindnest_core.settings import Settings
from mindnest_worker.chunking import chunk_segments
from mindnest_worker.parsing import IngestError, parse_document

EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}


def load_passages(corpus: Path, max_chars: int, overlap: int) -> tuple[list[PassageView], list[str]]:
    passages: list[PassageView] = []
    problems: list[str] = []
    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in EXTENSIONS and p.is_file())
    if not files:
        problems.append(f"no documents found under {corpus}")
    for path in files:
        try:
            parsed = parse_document(path.suffix.lower().lstrip("."), path.read_bytes())
        except IngestError as exc:
            problems.append(f"{path.name}: could not be read ({exc.code})")
            continue
        if parsed.needs_ocr:
            problems.append(f"{path.name}: needs OCR; its text cannot be checked offline")
            continue
        for chunk in chunk_segments(parsed.segments, max_chars, overlap):
            passages.append(PassageView(filename=path.name, text=chunk.text, page=chunk.page))
    return passages, problems


def main() -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=root / "datasets" / "rag_v2.jsonl")
    parser.add_argument("--corpus", type=Path, default=root / "corpus")
    args = parser.parse_args()

    settings = Settings()
    cases, errors = parse_dataset(args.dataset.read_text(encoding="utf-8"))
    if errors:
        print("The dataset is not valid:")
        for line in errors:
            print("  -", line)
        return 1

    passages, problems = load_passages(args.corpus, settings.chunk_max_chars, settings.chunk_overlap_chars)
    files = sorted({p.filename for p in passages})
    print(f"{len(cases)} questions, {len(passages)} passages from {len(files)} documents")

    by_language = Counter(c.language for c in cases)
    print("languages:", ", ".join(f"{k}={v}" for k, v in sorted(by_language.items())))
    print("unanswerable:", sum(not c.answerable for c in cases))

    for case in cases:
        for item in parse_evidence(case.evidence):
            # Wordings separated by "||" are alternatives; each one should exist somewhere.
            for wording in item.phrase.split(ALTERNATIVE_SEPARATOR):
                if wording.strip() and not _found(passages, Evidence(wording, item.file, item.page)):
                    where = f" in {item.file}" if item.file else ""
                    problems.append(f'{case.key}: wording not found in any one passage{where}: "{wording.strip()}"')
        if any(t.startswith("canary:") for t in case.tags) and not case.answerable:
            problems.append(f"{case.key}: a canary case should be answerable")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for line in problems:
            print("  -", line)
        return 1
    print("\nAll evidence phrases were found. The dataset matches the documents.")
    return 0


def _found(passages: list[PassageView], item: Evidence) -> bool:
    return any(matches_evidence(p, item) for p in passages)


if __name__ == "__main__":
    sys.exit(main())
