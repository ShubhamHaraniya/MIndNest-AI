"""The exam side of quizzes: a timed, autosaved attempt and an analytical result.

Everything is private to the signed-in student (row-level security). Nothing here changes how an
attempt is graded: `POST /attempts/{id}/submit` in `quizzes.py` still marks it. This module adds

* `GET  /attempts/{id}/session`    what the exam screen needs, with the server's clock;
* `PUT  /attempts/{id}/draft`      autosave of answers and the questions flagged for review;
* `GET  /attempts/{id}/analysis`   topic performance, history and revision data for a result;
* `POST /attempts/{id}/practise-missed`  a revision quiz made of the questions that were missed;
* `POST /quizzes/{id}/retry`       write a failed quiz again.

Per-attempt settings live in the quiz's JSON config (see `quizzes.SESSIONS_KEY`) because attempts
have no column for them.
"""

import json
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter
from mindnest_core.db import as_json
from mindnest_core.plannerlogic import local_zone
from mindnest_core.quizlogic import MAX_QUESTIONS, MAX_RESPONSE_CHARS, PASS_SCORE, percent
from mindnest_core.quizstore import CARD_DUE_SQL
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.quizzes import (
    GRACE,
    QuestionOut,
    QuizOut,
    _has_key,
    _quiz_out,
    _quiz_row,
    load_session_meta,
    save_session_meta,
)

router = APIRouter(tags=["quizzes"])

HISTORY_LIMIT = 50


# ------------------------------------------------------------------------------ schemas


class SessionOut(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    title: str
    subject_id: UUID | None
    subject_name: str | None
    language: str
    status: str
    started_at: datetime
    server_now: datetime
    limit_seconds: int | None
    remaining_seconds: int | None
    questions: list[QuestionOut]  # empty once the attempt is no longer in progress
    answers: dict[UUID, str]
    flags: list[UUID]


class DraftAnswer(BaseModel):
    question_id: UUID
    response: Annotated[str, StringConstraints(max_length=MAX_RESPONSE_CHARS)] = ""


class DraftIn(BaseModel):
    answers: list[DraftAnswer] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    flags: list[UUID] | None = Field(default=None, max_length=MAX_QUESTIONS)  # None = leave as is


class DraftOut(BaseModel):
    saved: int
    server_now: datetime
    remaining_seconds: int | None


class QuestionCard(BaseModel):
    box: int
    due_at: datetime
    times_seen: int
    times_correct: int


class QuestionInsight(BaseModel):
    question_id: UUID
    position: int
    score: float | None
    topic: str | None  # the source document's file name
    material_id: UUID | None
    card: QuestionCard | None


class TopicStat(BaseModel):
    topic: str | None
    material_id: UUID | None
    module: str | None
    answers: int
    points: float
    accuracy: float | None
    missed: int
    earlier_answers: int
    earlier_accuracy: float | None  # the same document in the course's earlier attempts
    cards: int
    cards_due: int


class HistoryPoint(BaseModel):
    attempt_id: UUID
    status: str
    points: float
    total: int
    unscored: int
    percent: float | None
    started_at: datetime
    submitted_at: datetime | None
    finished_at: datetime | None
    duration_seconds: int | None


class CourseStat(BaseModel):
    subject_id: UUID
    name: str
    attempts: int  # other completed attempts in the course
    average: float | None
    best: float | None
    cards_due: int


class RevisionStat(BaseModel):
    cards: int  # revision cards made from this quiz's questions
    due_now: int
    next_due_at: datetime | None


class AnalysisOut(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    quiz_title: str
    source: str
    status: str
    started_at: datetime
    submitted_at: datetime | None
    finished_at: datetime | None
    duration_seconds: int | None
    limit_seconds: int | None
    points: float
    total: int
    unscored: int
    percent: float | None
    missed: int
    questions: list[QuestionInsight]
    topics: list[TopicStat]
    history: list[HistoryPoint]
    course: CourseStat | None
    revision: RevisionStat


class PractiseIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None


# ------------------------------------------------------------------------------ helpers


async def _attempt_head(session: AsyncSession, attempt_id: UUID) -> Any:
    head = (
        (
            await session.execute(
                text(
                    "SELECT t.id, t.quiz_id, t.status, t.points, t.total, t.unscored, t.started_at, "
                    "t.submitted_at, t.finished_at, z.title, z.language, z.source, z.subject_id, "
                    "s.name AS subject_name, now() AS server_now "
                    "FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                    "LEFT JOIN subjects s ON s.id = z.subject_id WHERE t.id = :a"
                ),
                {"a": attempt_id},
            )
        )
        .mappings()
        .first()
    )
    if head is None:
        raise AppError(404, "not_found", "Attempt not found.")
    return head


def _remaining(head: Any, limit: int | None) -> int | None:
    if limit is None:
        return None
    left = limit - (head["server_now"] - head["started_at"]).total_seconds()
    return max(0, int(left))


def _limit(meta: dict[str, Any]) -> int | None:
    value = meta.get("limit_seconds")
    return value if isinstance(value, int) and value > 0 else None


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


# ------------------------------------------------------------------------------ the exam


@router.get("/attempts/{attempt_id}/session", response_model=SessionOut)
async def attempt_session(attempt_id: UUID, _user: AuthUser, db: UserDbDep) -> SessionOut:
    async with db.session() as session:
        head = await _attempt_head(session, attempt_id)
        meta = await load_session_meta(session, head["quiz_id"], attempt_id)
        limit = _limit(meta)
        questions: list[QuestionOut] = []
        answers: dict[UUID, str] = {}
        flags: list[UUID] = []
        if head["status"] == "in_progress":
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id, position, qtype, prompt, options FROM quiz_questions "
                            "WHERE quiz_id = :q ORDER BY position"
                        ),
                        {"q": head["quiz_id"]},
                    )
                )
                .mappings()
                .all()
            )
            questions = [
                QuestionOut(
                    id=r["id"], position=r["position"], qtype=r["qtype"], prompt=r["prompt"],
                    options=as_json(r["options"]),
                )
                for r in rows
            ]
            saved = (
                await session.execute(
                    text("SELECT question_id, response FROM quiz_answers WHERE attempt_id = :a"),
                    {"a": attempt_id},
                )
            ).all()
            answers = {row[0]: str(row[1]) for row in saved if str(row[1]) != ""}
            known = {q.id for q in questions}
            flags = [UUID(f) for f in meta.get("flags", []) if _is_uuid(f) and UUID(f) in known]
    return SessionOut(
        attempt_id=head["id"], quiz_id=head["quiz_id"], title=head["title"],
        subject_id=head["subject_id"], subject_name=head["subject_name"], language=head["language"],
        status=head["status"], started_at=head["started_at"], server_now=head["server_now"],
        limit_seconds=limit, remaining_seconds=_remaining(head, limit),
        questions=questions, answers=answers, flags=flags,
    )


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


@router.put("/attempts/{attempt_id}/draft", response_model=DraftOut)
async def save_draft(attempt_id: UUID, body: DraftIn, user: AuthUser, db: UserDbDep) -> DraftOut:
    async with db.session() as session:
        head = await _attempt_head(session, attempt_id)
        if head["status"] != "in_progress":
            raise AppError(409, "already_submitted", "This attempt has already been submitted.")
        meta = await load_session_meta(session, head["quiz_id"], attempt_id)
        limit = _limit(meta)
        if limit is not None and (head["server_now"] - head["started_at"]) > timedelta(seconds=limit) + GRACE:
            raise AppError(409, "time_up", "The time for this attempt has run out.")
        known = {
            r[0]
            for r in (
                await session.execute(
                    text("SELECT id FROM quiz_questions WHERE quiz_id = :q"), {"q": head["quiz_id"]}
                )
            ).all()
        }
        for item in body.answers:
            if item.question_id not in known:
                raise AppError(422, "validation_error", "An answer does not belong to this quiz.")
        if body.flags is not None and any(f not in known for f in body.flags):
            raise AppError(422, "validation_error", "A flag does not belong to this quiz.")
        for item in body.answers:
            await session.execute(
                text(
                    "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response) "
                    "VALUES (:a, :q, :u, :r) ON CONFLICT (attempt_id, question_id) "
                    "DO UPDATE SET response = EXCLUDED.response"
                ),
                {"a": attempt_id, "q": item.question_id, "u": user.id, "r": item.response},
            )
        if body.flags is not None:
            await save_session_meta(
                session, head["quiz_id"], attempt_id,
                {**meta, "flags": [str(f) for f in dict.fromkeys(body.flags)]},
            )
    return DraftOut(
        saved=len(body.answers), server_now=head["server_now"], remaining_seconds=_remaining(head, limit)
    )


# ------------------------------------------------------------------------------ the result


@router.get("/attempts/{attempt_id}/analysis", response_model=AnalysisOut)
async def attempt_analysis(attempt_id: UUID, user: AuthUser, db: UserDbDep) -> AnalysisOut:
    tz = local_zone(user.timezone).key
    async with db.session() as session:
        head = await _attempt_head(session, attempt_id)
        if head["status"] == "in_progress":
            raise AppError(409, "attempt_in_progress", "This attempt has not been submitted yet.")
        quiz_id, subject_id = head["quiz_id"], head["subject_id"]
        limit = _limit(await load_session_meta(session, quiz_id, attempt_id))

        rows = (
            (
                await session.execute(
                    text(
                        "SELECT q.id, q.position, q.source->>'filename' AS filename, "
                        "COALESCE(q.origin_question_id, q.id) AS card_key, a.score, "
                        "CASE WHEN q.source->>'chunk_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                        "THEN (SELECT c.material_id FROM chunks c WHERE c.id = CAST(q.source->>'chunk_id' AS uuid)) "
                        "END AS by_chunk, "
                        "(SELECT m.id FROM materials m WHERE m.subject_id = :s AND m.deleted_at IS NULL "
                        " AND m.filename = q.source->>'filename' ORDER BY m.created_at DESC LIMIT 1) AS by_name "
                        "FROM quiz_questions q LEFT JOIN quiz_answers a "
                        "ON a.question_id = q.id AND a.attempt_id = :a "
                        "WHERE q.quiz_id = :q ORDER BY q.position"
                    ),
                    {"a": attempt_id, "q": quiz_id, "s": subject_id},
                )
            )
            .mappings()
            .all()
        )
        material_ids = {r["by_chunk"] or r["by_name"] for r in rows} - {None}
        modules: dict[UUID, str | None] = {}
        live: set[UUID] = set()
        if material_ids:
            for m in (
                await session.execute(
                    text("SELECT id, module, deleted_at IS NULL AS live FROM materials WHERE id = ANY(CAST(:ids AS uuid[]))"),
                    {"ids": [str(i) for i in material_ids]},
                )
            ).all():
                modules[m[0]] = m[1]
                if m[2]:
                    live.add(m[0])

        cards = {
            r["origin_question_id"]: r
            for r in (
                await session.execute(
                    text(
                        "SELECT origin_question_id, box, due_at, times_seen, times_correct "
                        "FROM revision_cards WHERE origin_question_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [str(r["card_key"]) for r in rows]},
                )
            )
            .mappings()
            .all()
        }
        now = head["server_now"]

        insights: list[QuestionInsight] = []
        buckets: dict[str | None, dict[str, Any]] = {}
        for r in rows:
            material = r["by_chunk"] or r["by_name"]
            if material is not None and material not in live:
                material = None
            score = None if r["score"] is None else float(r["score"])
            card_row = cards.get(r["card_key"])
            insights.append(
                QuestionInsight(
                    question_id=r["id"], position=r["position"], score=score, topic=r["filename"],
                    material_id=material,
                    card=None if card_row is None else QuestionCard(
                        box=card_row["box"], due_at=card_row["due_at"],
                        times_seen=card_row["times_seen"], times_correct=card_row["times_correct"],
                    ),
                )
            )
            bucket = buckets.setdefault(
                r["filename"], {"material": None, "answers": 0, "points": 0.0, "missed": 0}
            )
            bucket["material"] = bucket["material"] or material
            if score is not None:
                bucket["answers"] += 1
                bucket["points"] += score
                if score < PASS_SCORE:
                    bucket["missed"] += 1

        names = [n for n in buckets if n is not None]
        earlier: dict[str, Any] = {}
        topic_cards: dict[str, Any] = {}
        if names and subject_id is not None:
            cut = head["finished_at"] or head["server_now"]
            earlier = {
                r["filename"]: r
                for r in (
                    await session.execute(
                        text(
                            "SELECT q.source->>'filename' AS filename, avg(a.score) AS acc, count(*) AS n "
                            "FROM quiz_answers a JOIN quiz_questions q ON q.id = a.question_id "
                            "JOIN quiz_attempts t ON t.id = a.attempt_id JOIN quizzes z ON z.id = t.quiz_id "
                            "WHERE a.score IS NOT NULL AND t.status = 'completed' AND z.subject_id = :s "
                            "AND t.id <> :a AND t.finished_at < :cut "
                            "AND q.source->>'filename' = ANY(CAST(:names AS text[])) "
                            "GROUP BY q.source->>'filename'"
                        ),
                        {"s": subject_id, "a": attempt_id, "cut": cut, "names": names},
                    )
                )
                .mappings()
                .all()
            }
            topic_cards = {
                r["filename"]: r
                for r in (
                    await session.execute(
                        text(
                            "SELECT source->>'filename' AS filename, count(*) AS cards, "
                            f"count(*) FILTER (WHERE {CARD_DUE_SQL}) AS due FROM revision_cards c "
                            "WHERE c.subject_id = :s AND c.source->>'filename' = ANY(CAST(:names AS text[])) "
                            "GROUP BY source->>'filename'"
                        ),
                        {"s": subject_id, "names": names, "tz": tz},
                    )
                )
                .mappings()
                .all()
            }

        topics = []
        for name, b in buckets.items():
            before = earlier.get(name) if name else None
            held = topic_cards.get(name) if name else None
            topics.append(
                TopicStat(
                    topic=name, material_id=b["material"], module=modules.get(b["material"]) if b["material"] else None,
                    answers=b["answers"], points=round(b["points"], 2),
                    accuracy=percent(b["points"], b["answers"]), missed=b["missed"],
                    earlier_answers=int(before["n"]) if before else 0,
                    earlier_accuracy=None if before is None else round(float(before["acc"]), 4),
                    cards=int(held["cards"]) if held else 0, cards_due=int(held["due"]) if held else 0,
                )
            )
        # Weakest first; documents with nothing marked go last, and "no source" after real documents.
        topics.sort(key=lambda x: (x.accuracy is None, x.topic is None, x.accuracy if x.accuracy is not None else 0, -x.answers))

        history_rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, status, points, total, unscored, started_at, submitted_at, finished_at "
                        "FROM quiz_attempts WHERE quiz_id = :q AND status <> 'in_progress' "
                        "ORDER BY COALESCE(submitted_at, finished_at, started_at) DESC LIMIT :n"
                    ),
                    {"q": quiz_id, "n": HISTORY_LIMIT},
                )
            )
            .mappings()
            .all()
        )
        history = [
            HistoryPoint(
                attempt_id=h["id"], status=h["status"], points=float(h["points"]), total=int(h["total"]),
                unscored=int(h["unscored"]), percent=percent(float(h["points"]), int(h["total"])),
                started_at=h["started_at"], submitted_at=h["submitted_at"], finished_at=h["finished_at"],
                duration_seconds=_seconds(h["started_at"], h["submitted_at"]),
            )
            for h in reversed(history_rows)
        ]

        course: CourseStat | None = None
        if subject_id is not None:
            figures = (
                (
                    await session.execute(
                        text(
                            "SELECT count(*) AS n, sum(t.points) AS p, sum(t.total) AS tot, "
                            "max(t.points / t.total) AS best FROM quiz_attempts t "
                            "JOIN quizzes z ON z.id = t.quiz_id WHERE z.subject_id = :s "
                            "AND t.status = 'completed' AND t.total > 0 AND t.id <> :a"
                        ),
                        {"s": subject_id, "a": attempt_id},
                    )
                )
                .mappings()
                .one()
            )
            due = (
                await session.execute(
                    text(f"SELECT count(*) FROM revision_cards c WHERE c.subject_id = :s AND {CARD_DUE_SQL}"),
                    {"s": subject_id, "tz": tz},
                )
            ).scalar_one()
            course = CourseStat(
                subject_id=subject_id, name=head["subject_name"] or "", attempts=int(figures["n"]),
                average=percent(float(figures["p"] or 0), int(figures["tot"] or 0)),
                best=None if figures["best"] is None else round(float(figures["best"]), 4),
                cards_due=int(due),
            )

    mine = [c for c in cards.values()]
    upcoming = [c["due_at"] for c in mine if c["due_at"] > now]
    return AnalysisOut(
        attempt_id=head["id"], quiz_id=quiz_id, quiz_title=head["title"], source=head["source"],
        status=head["status"], started_at=head["started_at"], submitted_at=head["submitted_at"],
        finished_at=head["finished_at"], duration_seconds=_seconds(head["started_at"], head["submitted_at"]),
        limit_seconds=limit, points=float(head["points"]), total=int(head["total"]),
        unscored=int(head["unscored"]), percent=percent(float(head["points"]), int(head["total"])),
        missed=sum(1 for q in insights if q.score is not None and q.score < PASS_SCORE),
        questions=insights, topics=topics, history=history, course=course,
        revision=RevisionStat(
            cards=len(mine), due_now=sum(1 for c in mine if c["due_at"] <= now),
            next_due_at=min(upcoming) if upcoming else None,
        ),
    )


# ------------------------------------------------------------------------------ follow-ups


@router.post("/attempts/{attempt_id}/practise-missed", status_code=201, response_model=QuizOut)
async def practise_missed(
    attempt_id: UUID, body: PractiseIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> QuizOut:
    """A new revision quiz from the questions this attempt got wrong (or only partly right)."""
    await limiter.check(f"quiz-create:{user.id}", 10, 60)
    async with db.session() as session:
        head = await _attempt_head(session, attempt_id)
        if head["status"] == "in_progress":
            raise AppError(409, "attempt_in_progress", "This attempt has not been submitted yet.")
        missed = (
            (
                await session.execute(
                    text(
                        "SELECT q.id, q.qtype, q.prompt, q.options, q.answer, q.explanation, q.source, "
                        "q.origin_question_id FROM quiz_questions q JOIN quiz_answers a "
                        "ON a.question_id = q.id AND a.attempt_id = :a "
                        "WHERE q.quiz_id = :q AND a.score IS NOT NULL AND a.score < :pass "
                        "ORDER BY q.position"
                    ),
                    {"a": attempt_id, "q": head["quiz_id"], "pass": PASS_SCORE},
                )
            )
            .mappings()
            .all()
        )
        if not missed:
            raise AppError(409, "nothing_missed", "There is nothing to practise from this attempt.")
        quiz_id = (
            await session.execute(
                text(
                    "INSERT INTO quizzes (user_id, subject_id, title, source, language, config, status, "
                    "question_count, finished_at) VALUES (:u, :s, :t, 'revision', :l, CAST(:c AS jsonb), "
                    "'ready', :n, now()) RETURNING id"
                ),
                {
                    "u": user.id, "s": head["subject_id"], "t": body.title or "Revision",
                    "l": head["language"], "n": len(missed),
                    "c": json.dumps({"count": len(missed), "revision": True, "retry_of": str(attempt_id)}),
                },
            )
        ).scalar_one()
        for position, q in enumerate(missed, start=1):
            await session.execute(
                text(
                    "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, options, "
                    "answer, explanation, source, origin_question_id) VALUES (:q, :u, :p, :t, :pr, "
                    "CAST(:o AS jsonb), :a, :e, CAST(:s AS jsonb), :origin)"
                ),
                {
                    "q": quiz_id, "u": user.id, "p": position, "t": q["qtype"], "pr": q["prompt"],
                    "o": None if q["options"] is None else json.dumps(as_json(q["options"]), ensure_ascii=False),
                    "a": q["answer"], "e": q["explanation"],
                    "s": None if q["source"] is None else json.dumps(as_json(q["source"]), ensure_ascii=False),
                    "origin": q["origin_question_id"] or q["id"],
                },
            )
        return _quiz_out(await _quiz_row(session, quiz_id))


@router.post("/quizzes/{quiz_id}/retry", response_model=QuizOut)
async def retry_quiz(
    quiz_id: UUID, user: AuthUser, db: UserDbDep, queue: QueueDep, limiter: LimiterDep
) -> QuizOut:
    """Write a failed quiz again with the settings it was created with."""
    await limiter.check(f"quiz-create:{user.id}", 10, 60)
    async with db.session() as session:
        current = (
            await session.execute(text("SELECT status FROM quizzes WHERE id = :q"), {"q": quiz_id})
        ).scalar_one_or_none()
        if current is None:
            raise AppError(404, "not_found", "Quiz not found.")
        if current != "failed":
            raise AppError(409, "not_failed", "Only a quiz that failed can be written again.")
        if await _has_key(session, None) is None:
            raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")
        await session.execute(text("DELETE FROM quiz_questions WHERE quiz_id = :q"), {"q": quiz_id})
        await session.execute(
            text(
                "UPDATE quizzes SET status = 'queued', error = NULL, finished_at = NULL, "
                "question_count = 0 WHERE id = :q"
            ),
            {"q": quiz_id},
        )
        out = _quiz_out(await _quiz_row(session, quiz_id))
    await queue.enqueue_quiz_generation(quiz_id, user.id)
    return out
