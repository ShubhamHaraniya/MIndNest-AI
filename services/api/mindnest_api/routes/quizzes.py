"""Quizzes made from a student's own materials, attempts at them, and spaced revision.

Everything is private to the signed-in student (row-level security). A quiz is written in the
background with the student's own AI key; multiple-choice and true/false answers are marked
immediately and short answers are marked by the AI in the background. The correct answers are
never sent to the browser until an attempt has been submitted.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from mindnest_core.db import as_json
from mindnest_core.quizlogic import (
    DIFFICULTIES,
    MAX_QUESTIONS,
    MAX_RESPONSE_CHARS,
    MIN_QUESTIONS,
    QUESTION_TYPES,
    grade_objective,
    is_objective,
    percent,
    quiz_display_status,
)
from mindnest_core.quizstore import CARD_DUE_SQL, finalize_attempt
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.llm import PROVIDERS, ProviderId

router = APIRouter(tags=["quizzes"])

MAX_LIMIT_MINUTES = 240
# Per-attempt settings (time limit, questions flagged for review) live in the quiz's JSON config
# under this key, keyed by attempt id, because attempts have no column for them. They are never
# sent to the browser as part of `config`.
SESSIONS_KEY = "sessions"
HIDDEN_CONFIG = {"chunk_ids", SESSIONS_KEY}

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Language = Literal["en", "hi", "gu"]


# ------------------------------------------------------------------------------ schemas


class QuizIn(BaseModel):
    subject_id: UUID
    title: Title | None = None
    count: int = Field(default=10, ge=MIN_QUESTIONS, le=MAX_QUESTIONS)
    types: list[str] = Field(default_factory=lambda: list(QUESTION_TYPES), min_length=1, max_length=3)
    difficulty: str = "medium"
    language: Language = "en"
    provider: ProviderId | None = None
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    # Optional default time limit for every attempt at this quiz (kept in the quiz's JSON config).
    time_limit_minutes: int | None = Field(default=None, ge=1, le=MAX_LIMIT_MINUTES)
    # Practise one document: only passages of this material (of the same subject) are used.
    material_id: UUID | None = None
    # "general" asks the AI about a topic from its own knowledge instead of the student's notes.
    basis: Literal["notes", "general"] = "notes"
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None


class StartIn(BaseModel):
    """Optional settings when an attempt is started; absent means the quiz's own default limit."""

    time_limit_minutes: int | None = Field(default=None, ge=0, le=MAX_LIMIT_MINUTES)  # 0 = no limit


class AttemptBrief(BaseModel):
    id: UUID
    status: str
    points: float
    total: int
    unscored: int
    percent: float | None
    finished_at: datetime | None


class QuizOut(BaseModel):
    id: UUID
    title: str
    source: str
    subject_id: UUID | None
    subject_name: str | None
    language: str
    status: str
    error: str | None
    question_count: int
    config: dict[str, Any]
    created_at: datetime
    attempts: int
    last_attempt: AttemptBrief | None
    best_percent: float | None = None
    open_attempt_id: UUID | None = None
    time_limit_minutes: int | None = None
    # The one status shown everywhere: ready | in_progress | completed | archived (or preparing /
    # failed while the quiz is still being written or could not be).
    display_status: str = "ready"
    archived_at: datetime | None = None
    # Questions the AI wrote that failed the checks (bad answer key, duplicate, ...) and were
    # discarded; 0 when none.
    rejected_count: int = 0


class QuestionOut(BaseModel):
    id: UUID
    position: int
    qtype: str
    prompt: str
    options: list[str] | None


class QuizDetail(QuizOut):
    questions: list[QuestionOut]


class AttemptStart(BaseModel):
    id: UUID
    quiz_id: UUID
    status: str


class AnswerIn(BaseModel):
    question_id: UUID
    response: Annotated[str, StringConstraints(max_length=MAX_RESPONSE_CHARS)] = ""


class SubmitIn(BaseModel):
    answers: list[AnswerIn] = Field(max_length=MAX_QUESTIONS)


class ResultOut(BaseModel):
    question_id: UUID
    position: int
    qtype: str
    prompt: str
    options: list[str] | None
    answer: str
    explanation: str | None
    source: dict[str, Any] | None
    response: str
    score: float | None
    feedback: str | None


class AttemptOut(BaseModel):
    id: UUID
    quiz_id: UUID
    quiz_title: str
    language: str
    status: str
    points: float
    total: int
    unscored: int
    percent: float | None
    started_at: datetime
    submitted_at: datetime | None
    finished_at: datetime | None
    results: list[ResultOut]


class RevisionIn(BaseModel):
    count: int = Field(default=10, ge=1, le=MAX_QUESTIONS)
    subject_id: UUID | None = None


# ------------------------------------------------------------------------------ helpers

_QUIZ_SQL = """
  SELECT z.id, z.title, z.source, z.subject_id, s.name AS subject_name, z.language, z.status,
         z.error, z.question_count, z.config, z.created_at, z.archived_at,
         (SELECT count(*) FROM quiz_attempts t WHERE t.quiz_id = z.id) AS attempts,
         (SELECT count(*) FROM quiz_attempts t
           WHERE t.quiz_id = z.id AND t.status <> 'in_progress') AS submitted,
         la.id AS la_id, la.status AS la_status, la.points AS la_points, la.total AS la_total,
         la.unscored AS la_unscored, la.finished_at AS la_finished,
         (SELECT max(t.points / NULLIF(t.total, 0)) FROM quiz_attempts t
           WHERE t.quiz_id = z.id AND t.status = 'completed') AS best,
         (SELECT t.id FROM quiz_attempts t WHERE t.quiz_id = z.id AND t.status = 'in_progress'
           ORDER BY t.started_at DESC LIMIT 1) AS open_attempt
  FROM quizzes z
  LEFT JOIN subjects s ON s.id = z.subject_id
  LEFT JOIN LATERAL (
    SELECT t.id, t.status, t.points, t.total, t.unscored, t.finished_at
    FROM quiz_attempts t WHERE t.quiz_id = z.id AND t.status <> 'in_progress'
    ORDER BY t.submitted_at DESC NULLS LAST, t.started_at DESC LIMIT 1
  ) la ON true
"""


def _brief(row: Any) -> AttemptBrief | None:
    if row["la_id"] is None:
        return None
    points = float(row["la_points"])
    return AttemptBrief(
        id=row["la_id"], status=row["la_status"], points=points, total=int(row["la_total"]),
        unscored=int(row["la_unscored"]), percent=percent(points, int(row["la_total"])),
        finished_at=row["la_finished"],
    )


def _quiz_out(row: Any) -> QuizOut:
    config = as_json(row["config"]) or {}
    limit = config.get("time_limit_minutes")
    best = row["best"]
    rejected = config.get("rejected")
    rejected_count = rejected.get("count") if isinstance(rejected, dict) else 0
    return QuizOut(
        id=row["id"], title=row["title"], source=row["source"], subject_id=row["subject_id"],
        subject_name=row["subject_name"], language=row["language"], status=row["status"],
        error=row["error"], question_count=int(row["question_count"]),
        config={k: v for k, v in config.items() if k not in HIDDEN_CONFIG and k != "rejected"},
        created_at=row["created_at"],
        attempts=int(row["attempts"]), last_attempt=_brief(row),
        best_percent=None if best is None else round(float(best), 4),
        open_attempt_id=row["open_attempt"], time_limit_minutes=limit if isinstance(limit, int) else None,
        display_status=quiz_display_status(
            status=row["status"], archived=row["archived_at"] is not None,
            open_attempt=row["open_attempt"] is not None, submitted_attempts=int(row["submitted"]),
        ),
        archived_at=row["archived_at"],
        rejected_count=rejected_count if isinstance(rejected_count, int) else 0,
    )


async def _quiz_row(session: AsyncSession, quiz_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_QUIZ_SQL} WHERE z.id = :id"), {"id": quiz_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Quiz not found.")
    return row


async def _has_key(session: AsyncSession, provider: str | None) -> tuple[str, str | None] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT provider, model FROM provider_keys "
                    "WHERE (CAST(:p AS text) IS NULL OR provider = :p) "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"p": provider},
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else (str(row["provider"]), row["model"])


async def save_session_meta(
    session: AsyncSession, quiz_id: UUID, attempt_id: UUID, meta: dict[str, Any]
) -> None:
    """Store one attempt's settings (time limit, flagged questions) in the quiz's JSON config."""
    await session.execute(
        text(
            "UPDATE quizzes SET config = jsonb_set("
            "config || jsonb_build_object(CAST(:k AS text), COALESCE(config->CAST(:k AS text), '{}'::jsonb)), "
            "ARRAY[CAST(:k AS text), CAST(:a AS text)], CAST(:m AS jsonb), true) WHERE id = :q"
        ),
        {"k": SESSIONS_KEY, "a": str(attempt_id), "m": json.dumps(meta), "q": quiz_id},
    )


async def load_session_meta(session: AsyncSession, quiz_id: UUID, attempt_id: UUID) -> dict[str, Any]:
    config = (
        await session.execute(text("SELECT config FROM quizzes WHERE id = :q"), {"q": quiz_id})
    ).scalar_one_or_none()
    meta = ((as_json(config) or {}).get(SESSIONS_KEY) or {}).get(str(attempt_id))
    return meta if isinstance(meta, dict) else {}


GRACE = timedelta(seconds=60)  # slack for a slow network around the end of a timed attempt


async def time_is_up(session: AsyncSession, quiz_id: UUID, attempt_id: UUID) -> bool:
    """True when the attempt has a time limit and it ran out (more than the grace ago)."""
    limit = (await load_session_meta(session, quiz_id, attempt_id)).get("limit_seconds")
    if not isinstance(limit, int) or limit <= 0:
        return False
    started = (
        await session.execute(
            text("SELECT started_at FROM quiz_attempts WHERE id = :a"), {"a": attempt_id}
        )
    ).scalar_one()
    return datetime.now(UTC) > started + timedelta(seconds=limit) + GRACE


# ------------------------------------------------------------------------------ quizzes


@router.get("/quizzes", response_model=list[QuizOut])
async def list_quizzes(_user: AuthUser, db: UserDbDep) -> list[QuizOut]:
    async with db.session() as session:
        rows = (
            (await session.execute(text(f"{_QUIZ_SQL} ORDER BY z.created_at DESC LIMIT 200")))
            .mappings()
            .all()
        )
    return [_quiz_out(r) for r in rows]


@router.post("/quizzes", status_code=201, response_model=QuizOut)
async def create_quiz(
    body: QuizIn, user: AuthUser, db: UserDbDep, queue: QueueDep, limiter: LimiterDep
) -> QuizOut:
    await limiter.check(f"quiz-create:{user.id}", 10, 60)
    types = [t for t in dict.fromkeys(body.types) if t in QUESTION_TYPES]
    if not types:
        raise AppError(422, "validation_error", "Choose at least one question type.")
    if body.difficulty not in DIFFICULTIES:
        raise AppError(422, "validation_error", "Unknown difficulty.")
    async with db.session() as session:
        subject = (
            await session.execute(
                text("SELECT name FROM subjects WHERE id = :s AND archived_at IS NULL"),
                {"s": body.subject_id},
            )
        ).scalar_one_or_none()
        if subject is None:
            raise AppError(404, "not_found", "Subject not found.")
        key = await _has_key(session, body.provider)
        if key is None:
            raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")
        provider, saved_model = key
        general = body.basis == "general"
        if general and (body.topic is None or body.material_id is not None):
            raise AppError(422, "validation_error", "A general-knowledge quiz needs a topic and no document.")
        ready = (
            await session.execute(
                text(
                    "SELECT count(*) FROM chunks c JOIN materials m ON m.id = c.material_id "
                    "WHERE c.is_active AND c.subject_id = :s AND m.deleted_at IS NULL "
                    "AND m.status = 'ready'"
                ),
                {"s": body.subject_id},
            )
        ).scalar_one()
        if not ready and not general:
            raise AppError(409, "no_materials", "This subject has no processed materials yet.")
        config: dict[str, Any] = {
            "count": body.count, "types": types, "difficulty": body.difficulty,
            "provider": provider, "model": body.model or saved_model or PROVIDERS[provider].default_model,
        }
        if body.time_limit_minutes:
            config["time_limit_minutes"] = body.time_limit_minutes
        if general:
            config |= {"basis": "general", "topic": body.topic, "subject_name": subject}
        if body.material_id is not None:
            material = (
                (
                    await session.execute(
                        text(
                            "SELECT id, filename FROM materials WHERE id = :m AND subject_id = :s "
                            "AND deleted_at IS NULL AND status = 'ready'"
                        ),
                        {"m": body.material_id, "s": body.subject_id},
                    )
                )
                .mappings()
                .first()
            )
            if material is None:
                raise AppError(404, "not_found", "Document not found.")
            chunk_ids = (
                await session.execute(
                    text(
                        "SELECT id FROM chunks WHERE material_id = :m AND is_active "
                        "ORDER BY random() LIMIT 600"
                    ),
                    {"m": body.material_id},
                )
            ).scalars().all()
            if not chunk_ids:
                raise AppError(409, "no_materials", "This document has no processed text yet.")
            config["chunk_ids"] = [str(c) for c in chunk_ids]
            config["material_id"] = str(material["id"])
            config["focus"] = material["filename"]
        quiz_id = (
            await session.execute(
                text(
                    "INSERT INTO quizzes (user_id, subject_id, title, language, config) "
                    "VALUES (:u, :s, :t, :l, CAST(:c AS jsonb)) RETURNING id"
                ),
                {
                    "u": user.id, "s": body.subject_id, "t": body.title or body.topic or f"{subject} quiz",
                    "l": body.language, "c": json.dumps(config),
                },
            )
        ).scalar_one()
        out = _quiz_out(await _quiz_row(session, quiz_id))
    # Enqueued after the commit, so the worker can always see the row.
    await queue.enqueue_quiz_generation(quiz_id, user.id)
    return out


@router.get("/quizzes/{quiz_id}", response_model=QuizDetail)
async def get_quiz(quiz_id: UUID, _user: AuthUser, db: UserDbDep) -> QuizDetail:
    async with db.session() as session:
        row = await _quiz_row(session, quiz_id)
        questions = (
            (
                await session.execute(
                    text(
                        "SELECT id, position, qtype, prompt, options FROM quiz_questions "
                        "WHERE quiz_id = :q ORDER BY position"
                    ),
                    {"q": quiz_id},
                )
            )
            .mappings()
            .all()
        )
    base = _quiz_out(row)
    return QuizDetail(
        **base.model_dump(),
        questions=[
            QuestionOut(
                id=q["id"], position=q["position"], qtype=q["qtype"], prompt=q["prompt"],
                options=as_json(q["options"]),
            )
            for q in questions
        ],
    )


class QuizPatch(BaseModel):
    archived: bool


@router.patch("/quizzes/{quiz_id}", response_model=QuizOut)
async def archive_quiz(quiz_id: UUID, body: QuizPatch, _user: AuthUser, db: UserDbDep) -> QuizOut:
    """Archive a quiz (it leaves the active list but keeps its attempts) or bring it back."""
    async with db.session() as session:
        result = await session.execute(
            text(
                "UPDATE quizzes SET archived_at = CASE WHEN CAST(:a AS boolean) "
                "THEN COALESCE(archived_at, now()) ELSE NULL END WHERE id = :id"
            ),
            {"a": body.archived, "id": quiz_id},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Quiz not found.")
        return _quiz_out(await _quiz_row(session, quiz_id))


@router.delete("/quizzes/{quiz_id}", status_code=204)
async def delete_quiz(quiz_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(text("DELETE FROM quizzes WHERE id = :id"), {"id": quiz_id})
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Quiz not found.")
    return Response(status_code=204)


# ------------------------------------------------------------------------------ attempts


@router.post("/quizzes/{quiz_id}/attempts", status_code=201, response_model=AttemptStart)
async def start_attempt(
    quiz_id: UUID, user: AuthUser, db: UserDbDep, body: StartIn | None = None
) -> AttemptStart:
    async with db.session() as session:
        found = (
            (
                await session.execute(
                    text("SELECT status, config, archived_at FROM quizzes WHERE id = :q"), {"q": quiz_id}
                )
            )
            .mappings()
            .first()
        )
        if found is None:
            raise AppError(404, "not_found", "Quiz not found.")
        status = found["status"]
        if status != "ready":
            raise AppError(409, "quiz_not_ready", "This quiz is not ready yet.")
        if found["archived_at"] is not None:
            raise AppError(409, "quiz_archived", "This quiz is archived. Restore it to take it again.")
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM quiz_attempts WHERE quiz_id = :q AND status = 'in_progress' "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"q": quiz_id},
            )
        ).scalar_one_or_none()
        if existing is not None:
            return AttemptStart(id=existing, quiz_id=quiz_id, status="in_progress")
        attempt_id = (
            await session.execute(
                text("INSERT INTO quiz_attempts (quiz_id, user_id) VALUES (:q, :u) RETURNING id"),
                {"q": quiz_id, "u": user.id},
            )
        ).scalar_one()
        # A limit chosen now wins over the quiz's own default; 0 means "no limit this time".
        default = (as_json(found["config"]) or {}).get("time_limit_minutes")
        minutes = body.time_limit_minutes if body is not None and body.time_limit_minutes is not None else default
        if isinstance(minutes, int) and minutes > 0:
            await save_session_meta(session, quiz_id, attempt_id, {"limit_seconds": minutes * 60})
    return AttemptStart(id=attempt_id, quiz_id=quiz_id, status="in_progress")


@router.get("/quizzes/{quiz_id}/attempts", response_model=list[AttemptBrief])
async def list_attempts(quiz_id: UUID, _user: AuthUser, db: UserDbDep) -> list[AttemptBrief]:
    async with db.session() as session:
        await _quiz_row(session, quiz_id)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, status, points, total, unscored, finished_at FROM quiz_attempts "
                        "WHERE quiz_id = :q AND status <> 'in_progress' "
                        "ORDER BY submitted_at DESC NULLS LAST LIMIT 50"
                    ),
                    {"q": quiz_id},
                )
            )
            .mappings()
            .all()
        )
    return [
        AttemptBrief(
            id=r["id"], status=r["status"], points=float(r["points"]), total=int(r["total"]),
            unscored=int(r["unscored"]), percent=percent(float(r["points"]), int(r["total"])),
            finished_at=r["finished_at"],
        )
        for r in rows
    ]


async def _attempt_out(session: AsyncSession, attempt_id: UUID) -> AttemptOut:
    head = (
        (
            await session.execute(
                text(
                    "SELECT t.id, t.quiz_id, t.status, t.points, t.total, t.unscored, t.started_at, "
                    "t.submitted_at, t.finished_at, z.title, z.language "
                    "FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id WHERE t.id = :a"
                ),
                {"a": attempt_id},
            )
        )
        .mappings()
        .first()
    )
    if head is None:
        raise AppError(404, "not_found", "Attempt not found.")
    results: list[ResultOut] = []
    if head["status"] != "in_progress":  # answers are only revealed after the attempt is submitted
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT q.id, q.position, q.qtype, q.prompt, q.options, q.answer, "
                        "q.explanation, q.source, a.response, a.score, a.feedback "
                        "FROM quiz_questions q LEFT JOIN quiz_answers a "
                        "ON a.question_id = q.id AND a.attempt_id = :a "
                        "WHERE q.quiz_id = :q ORDER BY q.position"
                    ),
                    {"a": attempt_id, "q": head["quiz_id"]},
                )
            )
            .mappings()
            .all()
        )
        results = [
            ResultOut(
                question_id=r["id"], position=r["position"], qtype=r["qtype"], prompt=r["prompt"],
                options=as_json(r["options"]), answer=r["answer"], explanation=r["explanation"],
                source=as_json(r["source"]), response=r["response"] or "",
                score=None if r["score"] is None else float(r["score"]), feedback=r["feedback"],
            )
            for r in rows
        ]
    points = float(head["points"])
    return AttemptOut(
        id=head["id"], quiz_id=head["quiz_id"], quiz_title=head["title"], language=head["language"],
        status=head["status"], points=points, total=int(head["total"]),
        unscored=int(head["unscored"]), percent=percent(points, int(head["total"])),
        started_at=head["started_at"], submitted_at=head["submitted_at"],
        finished_at=head["finished_at"], results=results,
    )


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
async def get_attempt(attempt_id: UUID, _user: AuthUser, db: UserDbDep) -> AttemptOut:
    async with db.session() as session:
        return await _attempt_out(session, attempt_id)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
async def submit_attempt(
    attempt_id: UUID, body: SubmitIn, user: AuthUser, db: UserDbDep, queue: QueueDep
) -> AttemptOut:
    grade_later = False
    async with db.session() as session:
        attempt = (
            (
                await session.execute(
                    text("SELECT quiz_id, status FROM quiz_attempts WHERE id = :a FOR UPDATE"),
                    {"a": attempt_id},
                )
            )
            .mappings()
            .first()
        )
        if attempt is None:
            raise AppError(404, "not_found", "Attempt not found.")
        if attempt["status"] != "in_progress":
            raise AppError(409, "already_submitted", "This attempt has already been submitted.")
        questions = (
            (
                await session.execute(
                    text("SELECT id, qtype, answer FROM quiz_questions WHERE quiz_id = :q"),
                    {"q": attempt["quiz_id"]},
                )
            )
            .mappings()
            .all()
        )
        known = {q["id"]: q for q in questions}
        responses: dict[UUID, str] = {}
        for item in body.answers:
            if item.question_id not in known:
                raise AppError(422, "validation_error", "An answer does not belong to this quiz.")
            responses[item.question_id] = item.response.strip()
        if await time_is_up(session, attempt["quiz_id"], attempt_id):
            # The limit ran out (plus a short grace) before this request: only what was saved while
            # time remained counts, so a timed attempt cannot be finished offline afterwards.
            saved = (
                await session.execute(
                    text("SELECT question_id, response FROM quiz_answers WHERE attempt_id = :a"),
                    {"a": attempt_id},
                )
            ).all()
            responses = {row[0]: str(row[1]).strip() for row in saved}

        short_to_mark = False
        for question_id, question in known.items():
            response = responses.get(question_id, "")
            score: float | None
            if is_objective(question["qtype"]):
                score = grade_objective(question["qtype"], question["answer"], response)
            elif not response:
                score = 0.0
            else:
                score = None
                short_to_mark = True
            await session.execute(
                text(
                    "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response, score) "
                    "VALUES (:a, :q, :u, :r, :s) ON CONFLICT (attempt_id, question_id) "
                    "DO UPDATE SET response = EXCLUDED.response, score = EXCLUDED.score, feedback = NULL"
                ),
                {"a": attempt_id, "q": question_id, "u": user.id, "r": response, "s": score},
            )
        await session.execute(
            text("UPDATE quiz_attempts SET submitted_at = now() WHERE id = :a"), {"a": attempt_id}
        )
        if short_to_mark and await _has_key(session, None) is not None:
            await session.execute(
                text("UPDATE quiz_attempts SET status = 'grading' WHERE id = :a"), {"a": attempt_id}
            )
            grade_later = True
        else:
            # Nothing for the AI to mark (or no key to mark with): finish now.
            await finalize_attempt(session, attempt_id, user.id)
        out = await _attempt_out(session, attempt_id)
    if grade_later:
        await queue.enqueue_attempt_grading(attempt_id, user.id)
    return out


# ------------------------------------------------------------------------------ revision


@router.post("/revision/start", status_code=201, response_model=QuizOut)
async def start_revision(body: RevisionIn, user: AuthUser, db: UserDbDep) -> QuizOut:
    async with db.session() as session:
        cards = (
            (
                await session.execute(
                    text(
                        "SELECT origin_question_id, subject_id, language, qtype, prompt, options, "
                        "answer, explanation, source FROM revision_cards "
                        "WHERE due_at <= now() AND (CAST(:s AS uuid) IS NULL OR subject_id = CAST(:s AS uuid)) "
                        "ORDER BY due_at, box LIMIT :n"
                    ),
                    {"s": str(body.subject_id) if body.subject_id else None, "n": body.count},
                )
            )
            .mappings()
            .all()
        )
        if not cards:
            raise AppError(409, "nothing_due", "Nothing is due for revision right now.")
        languages = [c["language"] for c in cards]
        language = max(set(languages), key=languages.count)
        config = {"count": len(cards), "revision": True}
        quiz_id = (
            await session.execute(
                text(
                    "INSERT INTO quizzes (user_id, subject_id, title, source, language, config, "
                    "status, question_count, finished_at) VALUES (:u, :s, 'Revision', 'revision', "
                    ":l, CAST(:c AS jsonb), 'ready', :n, now()) RETURNING id"
                ),
                {
                    "u": user.id, "s": body.subject_id, "l": language, "c": json.dumps(config),
                    "n": len(cards),
                },
            )
        ).scalar_one()
        for position, card in enumerate(cards, start=1):
            await session.execute(
                text(
                    "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, options, "
                    "answer, explanation, source, origin_question_id) VALUES (:q, :u, :p, :t, :pr, "
                    "CAST(:o AS jsonb), :a, :e, CAST(:s AS jsonb), :origin)"
                ),
                {
                    "q": quiz_id, "u": user.id, "p": position, "t": card["qtype"],
                    "pr": card["prompt"],
                    "o": json.dumps(as_json(card["options"]), ensure_ascii=False)
                    if card["options"] is not None else None,
                    "a": card["answer"], "e": card["explanation"],
                    "s": json.dumps(as_json(card["source"]), ensure_ascii=False)
                    if card["source"] is not None else None,
                    "origin": card["origin_question_id"],
                },
            )
        return _quiz_out(await _quiz_row(session, quiz_id))


# ------------------------------------------------------------------------------ progress


@router.get("/progress")
async def progress(user: AuthUser, db: UserDbDep) -> dict[str, Any]:
    tz = user.timezone or "UTC"
    async with db.session() as session:
        totals = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS attempts, sum(points) AS points, sum(total) AS total "
                        "FROM quiz_attempts WHERE status = 'completed' AND total > 0"
                    )
                )
            )
            .mappings()
            .one()
        )
        subjects = (
            (
                await session.execute(
                    text(
                        "SELECT z.subject_id, s.name, count(*) AS attempts, sum(t.points) AS points, "
                        "sum(t.total) AS total FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                        "LEFT JOIN subjects s ON s.id = z.subject_id "
                        "WHERE t.status = 'completed' AND t.total > 0 "
                        "GROUP BY z.subject_id, s.name ORDER BY max(t.finished_at) DESC LIMIT 20"
                    )
                )
            )
            .mappings()
            .all()
        )
        recent = (
            (
                await session.execute(
                    text(
                        "SELECT t.id, t.quiz_id, z.title, t.points, t.total, t.finished_at "
                        "FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                        "WHERE t.status = 'completed' AND t.total > 0 "
                        "ORDER BY t.finished_at DESC LIMIT 10"
                    )
                )
            )
            .mappings()
            .all()
        )
        cards = (
            (
                await session.execute(
                    text(
                        f"SELECT count(*) AS total, count(*) FILTER (WHERE {CARD_DUE_SQL}) AS due, "
                        f"min(c.due_at) FILTER (WHERE NOT {CARD_DUE_SQL}) AS next_due "
                        "FROM revision_cards c"
                    ),
                    {"tz": tz},
                )
            )
            .mappings()
            .one()
        )
        boxes = (
            await session.execute(text("SELECT box, count(*) FROM revision_cards GROUP BY box"))
        ).all()
        due_by_subject = (
            (
                await session.execute(
                    text(
                        "SELECT c.subject_id, s.name, count(*) AS due FROM revision_cards c "
                        f"LEFT JOIN subjects s ON s.id = c.subject_id WHERE {CARD_DUE_SQL} "
                        "GROUP BY c.subject_id, s.name ORDER BY count(*) DESC"
                    ),
                    {"tz": tz},
                )
            )
            .mappings()
            .all()
        )
    per_box = {str(i): 0 for i in range(1, 6)}
    for box, count in boxes:
        per_box[str(box)] = int(count)
    return {
        "attempts": int(totals["attempts"] or 0),
        "average": percent(float(totals["points"] or 0), int(totals["total"] or 0)),
        "subjects": [
            {
                "subject_id": str(r["subject_id"]) if r["subject_id"] else None,
                "name": r["name"], "attempts": int(r["attempts"]),
                "average": percent(float(r["points"]), int(r["total"])),
            }
            for r in subjects
        ],
        "recent": [
            {
                "attempt_id": str(r["id"]), "quiz_id": str(r["quiz_id"]), "title": r["title"],
                "percent": percent(float(r["points"]), int(r["total"])),
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in recent
        ],
        "revision": {
            "cards": int(cards["total"]), "due": int(cards["due"]),
            "next_due_at": cards["next_due"].isoformat() if cards["next_due"] else None,
            "boxes": per_box,
            "due_by_subject": [
                {
                    "subject_id": str(r["subject_id"]) if r["subject_id"] else None,
                    "name": r["name"], "due": int(r["due"]),
                }
                for r in due_by_subject
            ],
        },
    }
