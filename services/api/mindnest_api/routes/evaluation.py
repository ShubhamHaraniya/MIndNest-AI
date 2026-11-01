"""Evaluation Lab: datasets of questions, runs that score the search and answers, and results.

Everything is private to the signed-in student (row-level security), and runs only ever search
that student's own materials. Retrieval-only runs need no AI key. Provider keys are never
returned, stored in a run, or logged; the output shown here is passed through `redact` as well.
"""

import csv
import io
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from mindnest_core.db import as_json
from mindnest_core.evaldata import LANGUAGES, MAX_CASES, parse_case, parse_dataset
from mindnest_core.evalmetrics import (
    PassageView,
    matches_evidence,
    normalize_for_match,
    parse_evidence,
)
from mindnest_core.redact import redact
from mindnest_core.settings import get_settings
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.llm import PROVIDERS, ProviderId
from mindnest_api.retrieval import RETRIEVAL_MODES

router = APIRouter(prefix="/eval", tags=["evaluation"])

MODEL_NAME = re.compile(r"^[\w.:/\-]{1,100}$")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MAX_CHECK_CHUNKS = 30000


# ------------------------------------------------------------------------------ schemas


class DatasetOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    subject_id: UUID | None
    subject_name: str | None
    cases: int
    unanswerable: int
    languages: dict[str, int]
    created_at: datetime


class CaseOut(BaseModel):
    id: UUID
    key: str
    language: str
    question: str
    reference_answer: str | None
    answerable: bool
    evidence: list[dict[str, Any]]
    tags: list[str]


class DatasetDetail(DatasetOut):
    items: list[CaseOut]


class DatasetIn(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    subject_id: UUID | None = None
    # The text of a .jsonl file, one question per line.
    jsonl: str = Field(max_length=1_200_000)
    # Replace the questions of a dataset that already has this name.
    replace: bool = False


class CasePatch(BaseModel):
    question: str | None = None
    reference_answer: str | None = None
    answerable: bool | None = None
    evidence: list[dict[str, Any]] | None = None
    tags: list[str] | None = None
    language: str | None = None


class RunIn(BaseModel):
    dataset_id: UUID
    # One run is created per mode, so all four search methods can be compared in one click.
    modes: list[str] = Field(default_factory=lambda: ["advanced"], min_length=1, max_length=len(RETRIEVAL_MODES))
    top_k: int | None = Field(default=None, ge=1, le=20)
    candidates: int | None = Field(default=None, ge=5, le=100)
    # How the word search orders its matches (hybrid mode). None uses RETRIEVAL_KEYWORD_RANKER.
    keyword_ranker: Literal["ts_rank_cd", "bm25"] | None = None
    # Also write an answer for each question with the student's own key, and optionally judge it.
    generate: bool = False
    judge: bool = False
    provider: ProviderId | None = None
    model: str | None = None
    delay_seconds: float = Field(default=2.0, ge=0, le=60)
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None


class RunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    dataset_name: str | None
    label: str | None
    config: dict[str, Any]
    status: str
    total: int
    done: int
    summary: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ResultOut(BaseModel):
    case_key: str
    language: str
    question: str
    reference_answer: str | None
    answerable: bool
    retrieved: list[dict[str, Any]]
    answer: str | None
    scores: dict[str, Any]
    timings: dict[str, Any]
    error: str | None


# ------------------------------------------------------------------------------ helpers

_DATASET_SQL = """
  SELECT d.id, d.name, d.description, d.subject_id, s.name AS subject_name, d.created_at,
         (SELECT count(*) FROM eval_cases c WHERE c.dataset_id = d.id) AS cases,
         (SELECT count(*) FROM eval_cases c WHERE c.dataset_id = d.id AND NOT c.answerable)
           AS unanswerable
  FROM eval_datasets d LEFT JOIN subjects s ON s.id = d.subject_id
"""


async def _dataset(session: Any, dataset_id: UUID) -> DatasetOut:
    row = (
        (await session.execute(text(f"{_DATASET_SQL} WHERE d.id = :id"), {"id": dataset_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Dataset not found.")
    langs = (
        await session.execute(
            text("SELECT language, count(*) FROM eval_cases WHERE dataset_id = :id GROUP BY language"),
            {"id": dataset_id},
        )
    ).all()
    return DatasetOut(**row, languages={lang: int(n) for lang, n in langs})


def _case_out(row: Any) -> CaseOut:
    return CaseOut(
        id=row["id"],
        key=row["case_key"],
        language=row["language"],
        question=row["question"],
        reference_answer=row["reference_answer"],
        answerable=row["answerable"],
        evidence=as_json(row["evidence"]) or [],
        tags=list(row["tags"] or []),
    )


_CASE_COLUMNS = "id, case_key, language, question, reference_answer, answerable, evidence, tags"

_RUN_SQL = """
  SELECT r.id, r.dataset_id, d.name AS dataset_name, r.label, r.config, r.status, r.total, r.done,
         r.summary, r.error, r.created_at, r.started_at, r.finished_at
  FROM eval_runs r LEFT JOIN eval_datasets d ON d.id = r.dataset_id
"""


def _run_out(row: Any) -> RunOut:
    return RunOut(
        id=row["id"],
        dataset_id=row["dataset_id"],
        dataset_name=row["dataset_name"],
        label=row["label"],
        config=as_json(row["config"]) or {},
        status=row["status"],
        total=row["total"],
        done=row["done"],
        summary=as_json(row["summary"]),
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def _check_subject(session: Any, subject_id: UUID | None) -> None:
    if subject_id is None:
        return
    visible = (
        await session.execute(
            text("SELECT 1 FROM subjects WHERE id = :id AND archived_at IS NULL"), {"id": subject_id}
        )
    ).scalar_one_or_none()
    if visible is None:
        raise AppError(404, "not_found", "Subject not found.")


async def _insert_cases(session: Any, dataset_id: UUID, user_id: UUID, cases: list[Any]) -> None:
    for case in cases:
        await session.execute(
            text(
                "INSERT INTO eval_cases (dataset_id, user_id, case_key, language, question, "
                "reference_answer, answerable, evidence, tags) VALUES (:d, :u, :k, :l, :q, :r, :a, "
                "CAST(:e AS jsonb), CAST(:t AS text[])) "
                "ON CONFLICT (dataset_id, case_key) DO UPDATE SET language = EXCLUDED.language, "
                "question = EXCLUDED.question, reference_answer = EXCLUDED.reference_answer, "
                "answerable = EXCLUDED.answerable, evidence = EXCLUDED.evidence, tags = EXCLUDED.tags"
            ),
            {
                "d": dataset_id, "u": user_id, "k": case.key, "l": case.language,
                "q": case.question, "r": case.reference_answer, "a": case.answerable,
                "e": json.dumps(case.evidence, ensure_ascii=False), "t": case.tags,
            },
        )


# ------------------------------------------------------------------------------ datasets


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(_user: AuthUser, db: UserDbDep) -> list[DatasetOut]:
    async with db.session() as session:
        ids = (
            await session.execute(
                text("SELECT id FROM eval_datasets ORDER BY created_at DESC LIMIT 100")
            )
        ).scalars().all()
        return [await _dataset(session, dataset_id) for dataset_id in ids]


@router.post("/datasets", status_code=201, response_model=DatasetOut)
async def import_dataset(
    body: DatasetIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> DatasetOut:
    await limiter.check(f"eval-import:{user.id}", 20, 60)
    cases, errors = parse_dataset(body.jsonl)
    if errors:
        raise AppError(
            422, "invalid_dataset", "The question file has problems.", {"errors": errors}
        )
    async with db.session() as session:
        await _check_subject(session, body.subject_id)
        existing = (
            await session.execute(
                text("SELECT id FROM eval_datasets WHERE name = :n"), {"n": body.name}
            )
        ).scalar_one_or_none()
        if existing is not None and not body.replace:
            raise AppError(409, "dataset_exists", "A dataset with this name already exists.")
        if existing is None:
            dataset_id = (
                await session.execute(
                    text(
                        "INSERT INTO eval_datasets (user_id, subject_id, name, description) "
                        "VALUES (:u, :s, :n, :d) RETURNING id"
                    ),
                    {"u": user.id, "s": body.subject_id, "n": body.name, "d": body.description},
                )
            ).scalar_one()
        else:
            dataset_id = existing
            await session.execute(
                text("UPDATE eval_datasets SET subject_id = :s, description = :d WHERE id = :id"),
                {"s": body.subject_id, "d": body.description, "id": dataset_id},
            )
            await session.execute(
                text("DELETE FROM eval_cases WHERE dataset_id = :id AND NOT (case_key = ANY(:keys))"),
                {"id": dataset_id, "keys": [c.key for c in cases]},
            )
        await _insert_cases(session, dataset_id, user.id, cases)
        return await _dataset(session, dataset_id)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(dataset_id: UUID, _user: AuthUser, db: UserDbDep) -> DatasetDetail:
    async with db.session() as session:
        dataset = await _dataset(session, dataset_id)
        rows = (
            (
                await session.execute(
                    text(f"SELECT {_CASE_COLUMNS} FROM eval_cases WHERE dataset_id = :id ORDER BY case_key"),
                    {"id": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return DatasetDetail(**dataset.model_dump(), items=[_case_out(r) for r in rows])


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(
            text("DELETE FROM eval_datasets WHERE id = :id"), {"id": dataset_id}
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Dataset not found.")
    return Response(status_code=204)


@router.patch("/datasets/{dataset_id}/cases/{case_id}", response_model=CaseOut)
async def edit_case(
    dataset_id: UUID, case_id: UUID, body: CasePatch, _user: AuthUser, db: UserDbDep
) -> CaseOut:
    """Hand-edit one question. The merged result is validated like an imported line."""
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(f"SELECT {_CASE_COLUMNS} FROM eval_cases WHERE id = :c AND dataset_id = :d"),
                    {"c": case_id, "d": dataset_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AppError(404, "not_found", "Question not found.")
        current = _case_out(row)
        merged = {
            "id": current.key,
            "language": body.language if body.language is not None else current.language,
            "question": body.question if body.question is not None else current.question,
            "reference_answer": (
                body.reference_answer if body.reference_answer is not None else current.reference_answer
            ),
            "answerable": body.answerable if body.answerable is not None else current.answerable,
            "evidence": body.evidence if body.evidence is not None else current.evidence,
            "tags": body.tags if body.tags is not None else current.tags,
        }
        case, reason = parse_case(merged)
        if case is None:
            raise AppError(422, "invalid_case", f"That edit is not valid: {reason}.")
        await session.execute(
            text(
                "UPDATE eval_cases SET language = :l, question = :q, reference_answer = :r, "
                "answerable = :a, evidence = CAST(:e AS jsonb), tags = CAST(:t AS text[]) WHERE id = :c"
            ),
            {
                "l": case.language, "q": case.question, "r": case.reference_answer,
                "a": case.answerable, "e": json.dumps(case.evidence, ensure_ascii=False),
                "t": case.tags, "c": case_id,
            },
        )
        updated = (
            (
                await session.execute(
                    text(f"SELECT {_CASE_COLUMNS} FROM eval_cases WHERE id = :c"), {"c": case_id}
                )
            )
            .mappings()
            .one()
        )
    return _case_out(updated)


@router.get("/datasets/{dataset_id}/check")
async def check_dataset(dataset_id: UUID, _user: AuthUser, db: UserDbDep) -> dict[str, Any]:
    """Is each evidence phrase actually present in the student's processed materials?

    Run this after uploading the corpus: a phrase that is not found can never be retrieved, so
    it would only drag the scores down for a reason that has nothing to do with search quality.
    """
    async with db.session() as session:
        dataset = await _dataset(session, dataset_id)
        cases = (
            (
                await session.execute(
                    text(f"SELECT {_CASE_COLUMNS} FROM eval_cases WHERE dataset_id = :id ORDER BY case_key"),
                    {"id": dataset_id},
                )
            )
            .mappings()
            .all()
        )
        chunks = (
            (
                await session.execute(
                    text(
                        "SELECT m.filename, c.text FROM chunks c JOIN materials m ON m.id = c.material_id "
                        "WHERE c.is_active AND m.deleted_at IS NULL AND m.status = 'ready' "
                        "AND (CAST(:s AS uuid) IS NULL OR c.subject_id = CAST(:s AS uuid)) "
                        "LIMIT :n"
                    ),
                    {"s": str(dataset.subject_id) if dataset.subject_id else None, "n": MAX_CHECK_CHUNKS},
                )
            )
            .mappings()
            .all()
        )
    views = [PassageView(c["filename"], c["text"]) for c in chunks]
    files = sorted({v.filename for v in views})
    report: list[dict[str, Any]] = []
    for row in cases:
        evidence = parse_evidence(as_json(row["evidence"]))
        found = [
            {
                "phrase": e.phrase, "file": e.file,
                "found": any(matches_evidence(v, e) for v in views),
                "normalized_chars": len(normalize_for_match(e.phrase.replace("||", ""))),
            }
            for e in evidence
        ]
        report.append(
            {
                "key": row["case_key"], "language": row["language"], "answerable": row["answerable"],
                "evidence": found, "ok": all(f["found"] for f in found),
            }
        )
    return {
        "materials": files,
        "chunks": len(views),
        "ok": sum(1 for r in report if r["ok"]),
        "missing": sum(1 for r in report if not r["ok"]),
        "cases": report,
    }


# ------------------------------------------------------------------------------ runs


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    _user: AuthUser, db: UserDbDep, dataset_id: Annotated[UUID | None, Query()] = None
) -> list[RunOut]:
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"{_RUN_SQL} WHERE (CAST(:d AS uuid) IS NULL OR r.dataset_id = CAST(:d AS uuid)) "
                        "ORDER BY r.created_at DESC LIMIT 100"
                    ),
                    {"d": str(dataset_id) if dataset_id else None},
                )
            )
            .mappings()
            .all()
        )
    return [_run_out(r) for r in rows]


@router.post("/runs", status_code=201, response_model=list[RunOut])
async def start_runs(
    body: RunIn, user: AuthUser, db: UserDbDep, queue: QueueDep, limiter: LimiterDep
) -> list[RunOut]:
    settings = get_settings()
    await limiter.check(f"eval-run:{user.id}", 10, 60)
    modes = list(dict.fromkeys(body.modes))
    if any(m not in RETRIEVAL_MODES for m in modes):
        raise AppError(422, "validation_error", "Unknown search mode.")
    if body.judge and not body.generate:
        raise AppError(422, "validation_error", "Judging needs answers to be generated.")
    if body.model is not None and not MODEL_NAME.match(body.model):
        raise AppError(422, "validation_error", "That model name is not valid.")

    provider: str | None = None
    model: str | None = None
    async with db.session() as session:
        dataset = await _dataset(session, body.dataset_id)
        if dataset.cases == 0:
            raise AppError(409, "empty_dataset", "This dataset has no questions.")
        if body.generate:
            key_row = (
                (
                    await session.execute(
                        text(
                            "SELECT provider, model FROM provider_keys "
                            "WHERE (CAST(:p AS text) IS NULL OR provider = :p) "
                            "ORDER BY updated_at DESC LIMIT 1"
                        ),
                        {"p": body.provider},
                    )
                )
                .mappings()
                .first()
            )
            if key_row is None:
                raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")
            provider = str(key_row["provider"])
            model = body.model or key_row["model"] or PROVIDERS[provider].default_model
        ready = (
            await session.execute(
                text(
                    "SELECT count(*) FROM chunks c JOIN materials m ON m.id = c.material_id "
                    "WHERE c.is_active AND m.deleted_at IS NULL AND m.status = 'ready' "
                    "AND (CAST(:s AS uuid) IS NULL OR c.subject_id = CAST(:s AS uuid))"
                ),
                {"s": str(dataset.subject_id) if dataset.subject_id else None},
            )
        ).scalar_one()
        if not ready:
            raise AppError(
                409, "no_materials",
                "The dataset's subject has no processed materials. Upload the corpus first.",
            )
        run_ids: list[UUID] = []
        for mode in modes:
            config = {
                "mode": mode,
                "top_k": body.top_k or settings.retrieval_top_k,
                "candidates": body.candidates or settings.retrieval_candidates,
                "keyword_ranker": body.keyword_ranker or settings.retrieval_keyword_ranker,
                "generate": body.generate,
                "judge": body.judge,
                "provider": provider,
                "model": model,
                "judge_model": model if body.judge else None,
                "delay_seconds": body.delay_seconds if body.generate else 0,
            }
            run_id = (
                await session.execute(
                    text(
                        "INSERT INTO eval_runs (user_id, dataset_id, label, config, total) "
                        "VALUES (:u, :d, :l, CAST(:c AS jsonb), :t) RETURNING id"
                    ),
                    {
                        "u": user.id, "d": body.dataset_id, "l": body.label,
                        "c": json.dumps(config), "t": dataset.cases,
                    },
                )
            ).scalar_one()
            run_ids.append(run_id)
        rows = (
            (
                await session.execute(
                    text(f"{_RUN_SQL} WHERE r.id = ANY(:ids) ORDER BY r.created_at, r.id"),
                    {"ids": run_ids},
                )
            )
            .mappings()
            .all()
        )
        # Rows of one transaction share a created_at, so keep the order the modes were asked in.
        runs = sorted((_run_out(r) for r in rows), key=lambda r: run_ids.index(r.id))
    # Enqueued after the commit, so the worker can always see the rows.
    for run in runs:
        await queue.enqueue_evaluation(run.id, user.id)
    return runs


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: UUID, _user: AuthUser, db: UserDbDep) -> RunOut:
    async with db.session() as session:
        row = (
            (await session.execute(text(f"{_RUN_SQL} WHERE r.id = :id"), {"id": run_id}))
            .mappings()
            .first()
        )
    if row is None:
        raise AppError(404, "not_found", "Run not found.")
    out = _run_out(row)
    out.error = redact(out.error) if out.error else None
    return out


@router.get("/runs/{run_id}/results", response_model=list[ResultOut])
async def run_results(run_id: UUID, _user: AuthUser, db: UserDbDep) -> list[ResultOut]:
    async with db.session() as session:
        exists = (
            await session.execute(text("SELECT 1 FROM eval_runs WHERE id = :id"), {"id": run_id})
        ).scalar_one_or_none()
        if exists is None:
            raise AppError(404, "not_found", "Run not found.")
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT c.case_key, c.language, c.question, c.reference_answer, c.answerable, "
                        "r.retrieved, r.answer, r.scores, r.timings, r.error "
                        "FROM eval_results r JOIN eval_cases c ON c.id = r.case_id "
                        "WHERE r.run_id = :id ORDER BY c.case_key LIMIT :n"
                    ),
                    {"id": run_id, "n": MAX_CASES},
                )
            )
            .mappings()
            .all()
        )
    return [
        ResultOut(
            case_key=r["case_key"],
            language=r["language"],
            question=r["question"],
            reference_answer=r["reference_answer"],
            answerable=r["answerable"],
            retrieved=as_json(r["retrieved"]) or [],
            # Defence in depth: nothing shaped like a provider key is ever shown.
            answer=redact(r["answer"]) if r["answer"] else None,
            scores=as_json(r["scores"]) or {},
            timings=as_json(r["timings"]) or {},
            error=r["error"],
        )
        for r in rows
    ]


# ------------------------------------------------------------------------------ export

_EXPORT_FORMATS = ("json", "questions_csv", "passages_csv")


def _cell(value: Any) -> str:
    """One spreadsheet cell. A leading = + - @ would be run as a formula by Excel, so it is escaped."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text_value = str(value)
    if text_value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text_value
    return text_value


def _csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    # The byte-order mark makes Excel read Hindi and Gujarati text correctly.
    return buffer.getvalue().encode("utf-8-sig")


def _first_relevant_rank(retrieved: list[dict[str, Any]]) -> int | None:
    for item in retrieved:
        if item.get("relevant"):
            return int(item.get("n") or 0) or None
    return None


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: UUID,
    _user: AuthUser,
    db: UserDbDep,
    format: Annotated[str, Query()] = "json",  # noqa: A002 - the query parameter is called format
) -> Response:
    if format not in _EXPORT_FORMATS:
        raise AppError(422, "invalid_format", "Choose json, questions_csv or passages_csv.")
    async with db.session() as session:
        run_row = (
            (await session.execute(text(f"{_RUN_SQL} WHERE r.id = :id"), {"id": run_id}))
            .mappings()
            .first()
        )
        if run_row is None:
            raise AppError(404, "not_found", "Run not found.")
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT c.case_key, c.language, c.question, c.reference_answer, c.answerable, "
                        "c.evidence, c.tags, r.retrieved, r.answer, r.scores, r.timings, r.error "
                        "FROM eval_results r JOIN eval_cases c ON c.id = r.case_id "
                        "WHERE r.run_id = :id ORDER BY c.case_key LIMIT :n"
                    ),
                    {"id": run_id, "n": MAX_CASES},
                )
            )
            .mappings()
            .all()
        )
    run = _run_out(run_row)
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "case_key": r["case_key"],
                "language": r["language"],
                "answerable": r["answerable"],
                "tags": list(r["tags"] or []),
                "question": r["question"],
                "reference_answer": r["reference_answer"],
                "evidence": as_json(r["evidence"]) or [],
                "retrieved": as_json(r["retrieved"]) or [],
                # Defence in depth: nothing shaped like a provider key leaves the system.
                "answer": redact(r["answer"]) if r["answer"] else None,
                "scores": as_json(r["scores"]) or {},
                "timings": as_json(r["timings"]) or {},
                "error": redact(r["error"]) if r["error"] else None,
            }
        )

    stem = f"mindnest-eval-{(run.label or run.config.get('mode') or 'run')}-{str(run.id)[:8]}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")[:80]

    if format == "json":
        payload = {
            "exported_at": datetime.now(UTC).isoformat(),
            "note": "Scores are 0 to 1. retrieved[].relevant says whether that passage contains an "
            "evidence phrase. Passage text is stored up to a fixed length.",
            "run": json.loads(run.model_dump_json()),
            "results": items,
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        media, filename = "application/json; charset=utf-8", f"{stem}.json"
    elif format == "questions_csv":
        score_keys = sorted({k for it in items for k in it["scores"]})
        timing_keys = sorted({k for it in items for k in it["timings"]})
        header = [
            "case_key", "language", "answerable", "tags", "question", "reference_answer",
            "evidence_phrases", "first_relevant_rank", "retrieved_count", "retrieved_files",
            "answer", "error",
            *[f"score_{k}" for k in score_keys],
            *[f"timing_{k}" for k in timing_keys],
        ]
        out_rows = []
        for it in items:
            retrieved = it["retrieved"]
            files = " | ".join(
                f"{x.get('n')}. {x.get('filename')}"
                + (f" p.{x['page']}" if x.get("page") is not None else "")
                + (" [relevant]" if x.get("relevant") else "")
                for x in retrieved
            )
            out_rows.append(
                [
                    it["case_key"], it["language"], it["answerable"], ";".join(it["tags"]),
                    it["question"], it["reference_answer"],
                    " | ".join(str(e.get("phrase", "")) for e in it["evidence"]),
                    _first_relevant_rank(retrieved), len(retrieved), files,
                    it["answer"], it["error"],
                    *[it["scores"].get(k) for k in score_keys],
                    *[it["timings"].get(k) for k in timing_keys],
                ]
            )
        body = _csv_bytes(header, out_rows)
        media, filename = "text/csv; charset=utf-8", f"{stem}-questions.csv"
    else:
        header = [
            "case_key", "language", "question", "rank", "filename", "page", "score", "relevant", "text",
        ]
        out_rows = [
            [
                it["case_key"], it["language"], it["question"], x.get("n"), x.get("filename"),
                x.get("page"), x.get("score"), bool(x.get("relevant")), x.get("text"),
            ]
            for it in items
            for x in it["retrieved"]
        ]
        body = _csv_bytes(header, out_rows)
        media, filename = "text/csv; charset=utf-8", f"{stem}-passages.csv"

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: UUID, user: AuthUser, db: UserDbDep) -> RunOut:
    async with db.session() as session:
        await session.execute(
            text(
                "UPDATE eval_runs SET status = 'cancelled', finished_at = now() "
                "WHERE id = :id AND status IN ('queued', 'running')"
            ),
            {"id": run_id},
        )
    return await get_run(run_id, user, db)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(text("DELETE FROM eval_runs WHERE id = :id"), {"id": run_id})
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Run not found.")
    return Response(status_code=204)


@router.get("/options")
async def options(_user: AuthUser) -> dict[str, Any]:
    return {"modes": list(RETRIEVAL_MODES), "languages": list(LANGUAGES), "max_cases": MAX_CASES}
