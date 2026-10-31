"""Extra figures for the course workspace: analytics, the course's assignments, renaming a module,
and "recommended next".

Read-only except the module rename. Everything runs inside `db.session()`, so row-level security
limits it to the signed-in student, and a course that belongs to someone else answers 404. The
rules (trend, coverage, progress, what to do next) are `mindnest_core.subjectlogic`; this file
only fetches the numbers and hands them over.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from mindnest_core.plannerlogic import local_today
from mindnest_core.quizstore import CARD_DUE_SQL
from mindnest_core.subjectlogic import (
    Deadline,
    ProgressInputs,
    Signals,
    WeakTopic,
    accuracy_trend,
    clean_optional_label,
    course_progress,
    material_coverage,
    name_key,
    progress_parts,
    recommend_next,
    share,
)
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.assignments import _LIST_SQL, AssignmentOut, _out
from mindnest_api.routes.courses import _require_course, course_overview
from mindnest_api.routes.courses import course_progress as progress_of

router = APIRouter(tags=["courses"])

ATTEMPTS_SHOWN = 20
WEEKS_SHOWN = 8


# ------------------------------------------------------------------------------ schemas


class AttemptPoint(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    quiz_title: str
    finished_at: datetime
    points: float
    total: int
    percent: float  # 0..1


class TypeAccuracy(BaseModel):
    qtype: str
    answers: int
    accuracy: float | None


class WeekPoint(BaseModel):
    week_start: date
    attempts: int
    answers: int
    accuracy: float | None


class CoverageOut(BaseModel):
    documents: int
    documents_ready: int
    documents_practised: int
    practised_share: float | None  # practised out of ready files
    modules_with_files: int
    modules_practised: int


class ProgressPartOut(BaseModel):
    key: str
    value: float | None
    weight: float


class AssignmentFigures(BaseModel):
    todo: int
    in_progress: int
    done: int
    overdue: int
    next_due_at: datetime | None
    next_due_title: str | None


class RevisionFigures(BaseModel):
    cards: int
    due: int


class RecommendationOut(BaseModel):
    kind: str
    priority: int
    ref_id: str | None
    label: str | None
    params: dict[str, int | float | str]


class CourseAnalytics(BaseModel):
    attempts: list[AttemptPoint]  # oldest first
    trend: str | None  # improving | steady | declining; None until four attempts
    by_type: list[TypeAccuracy]
    weeks: list[WeekPoint]  # oldest first, always WEEKS_SHOWN entries
    coverage: CoverageOut
    progress: float | None  # 0..1, None until a quiz or a study task says something
    progress_parts: list[ProgressPartOut]
    assignments: AssignmentFigures
    revision: RevisionFigures
    recommendations: list[RecommendationOut]


class ModuleRenameIn(BaseModel):
    old: str | None = Field(default=None, max_length=200)  # None: files that are in no module
    new: str | None = Field(default=None, max_length=200)  # None or blank: take them out of the module


class ModuleRenameOut(BaseModel):
    updated: int


# ------------------------------------------------------------------------------ analytics


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def recent_weeks(today: date, count: int = WEEKS_SHOWN) -> list[date]:
    """The Mondays of the last `count` weeks, oldest first, ending with this week."""
    this = monday_of(today)
    return [this - timedelta(weeks=n) for n in range(count - 1, -1, -1)]


@router.get("/subjects/{subject_id}/analytics", response_model=CourseAnalytics)
async def course_analytics(subject_id: UUID, user: AuthUser, db: UserDbDep) -> CourseAnalytics:
    """How the course is going: quiz scores over time, accuracy by question type, weekly practice,
    how much of the course has been read and tried, assignments, cards due, and what to do next."""
    tz = user.timezone
    now = datetime.now(UTC)
    today = local_today(tz, now)
    weeks = recent_weeks(today)

    overview = await course_overview(subject_id, user, db)
    progress = await progress_of(subject_id, user, db)
    figures = overview.course

    async with db.session() as session:
        await _require_course(session, subject_id)
        attempt_rows = (
            (
                await session.execute(
                    text(
                        "SELECT t.id AS attempt_id, z.id AS quiz_id, z.title, t.finished_at, t.points, "
                        "t.total FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                        "WHERE z.subject_id = :id AND t.status = 'completed' AND t.total > 0 "
                        "AND t.finished_at IS NOT NULL ORDER BY t.finished_at DESC LIMIT :n"
                    ),
                    {"id": subject_id, "n": ATTEMPTS_SHOWN},
                )
            )
            .mappings()
            .all()
        )
        type_rows = (
            (
                await session.execute(
                    text(
                        "SELECT q.qtype, count(*) AS answers, sum(a.score) AS score "
                        "FROM quiz_answers a JOIN quiz_questions q ON q.id = a.question_id "
                        "JOIN quiz_attempts t ON t.id = a.attempt_id JOIN quizzes z ON z.id = q.quiz_id "
                        "WHERE z.subject_id = :id AND a.score IS NOT NULL AND t.status = 'completed' "
                        "GROUP BY q.qtype ORDER BY q.qtype"
                    ),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
        week_rows = (
            (
                await session.execute(
                    text(
                        "SELECT date_trunc('week', t.finished_at AT TIME ZONE :tz)::date AS week, "
                        "count(*) AS attempts, sum(t.total) AS answers, sum(t.points) AS points "
                        "FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                        "WHERE z.subject_id = :id AND t.status = 'completed' AND t.total > 0 "
                        "AND (t.finished_at AT TIME ZONE :tz)::date >= :since GROUP BY 1"
                    ),
                    {"id": subject_id, "tz": tz, "since": weeks[0]},
                )
            )
            .mappings()
            .all()
        )
        files = (
            (
                await session.execute(
                    text(
                        "SELECT filename, module, status FROM materials "
                        "WHERE subject_id = :id AND deleted_at IS NULL"
                    ),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
        practised_rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT q.source->>'filename' FROM quiz_answers a "
                    "JOIN quiz_questions q ON q.id = a.question_id "
                    "JOIN quiz_attempts t ON t.id = a.attempt_id JOIN quizzes z ON z.id = q.quiz_id "
                    "WHERE z.subject_id = :id AND a.score IS NOT NULL AND t.status = 'completed' "
                    "AND q.source->>'filename' IS NOT NULL"
                ),
                {"id": subject_id},
            )
        ).all()
        assignment_rows = (
            (
                await session.execute(
                    text("SELECT id, title, due_at, status FROM assignments WHERE subject_id = :id"),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
        cards = (
            (
                await session.execute(
                    text(
                        f"SELECT count(*) AS cards, count(*) FILTER (WHERE {CARD_DUE_SQL}) AS due "
                        "FROM revision_cards c WHERE c.subject_id = :id"
                    ),
                    {"id": subject_id, "tz": tz},
                )
            )
            .mappings()
            .one()
        )
        task_rows = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE status = 'done') AS done, "
                        "count(*) FILTER (WHERE status = 'todo' AND planned_for <= :today) AS open "
                        "FROM study_tasks WHERE subject_id = :id"
                    ),
                    {"id": subject_id, "today": today},
                )
            )
            .mappings()
            .one()
        )

    # --- quiz scores over time
    chronological = list(reversed(attempt_rows))
    attempts = [
        AttemptPoint(
            attempt_id=r["attempt_id"], quiz_id=r["quiz_id"], quiz_title=r["title"],
            finished_at=r["finished_at"], points=float(r["points"]), total=int(r["total"]),
            percent=round(float(r["points"]) / int(r["total"]), 4),
        )
        for r in chronological
    ]
    trend = accuracy_trend([a.percent for a in attempts])

    by_type = [
        TypeAccuracy(
            qtype=r["qtype"], answers=int(r["answers"]),
            accuracy=round(float(r["score"]) / int(r["answers"]), 4) if int(r["answers"]) else None,
        )
        for r in type_rows
    ]

    by_week = {r["week"]: r for r in week_rows}
    week_points: list[WeekPoint] = []
    for monday in weeks:
        hit = by_week.get(monday)
        answers = int(hit["answers"]) if hit else 0
        week_points.append(
            WeekPoint(
                week_start=monday, attempts=int(hit["attempts"]) if hit else 0, answers=answers,
                accuracy=round(float(hit["points"]) / answers, 4) if hit and answers else None,
            )
        )

    # --- coverage and progress
    coverage = material_coverage(
        [(f["filename"], f["module"], f["status"]) for f in files], {r[0] for r in practised_rows}
    )
    inputs = ProgressInputs(
        documents=figures.documents, documents_ready=figures.documents_ready,
        quiz_attempts=figures.quiz_attempts, quiz_accuracy=figures.quiz_average,
        tasks_total=int(task_rows["done"]) + int(task_rows["open"]), tasks_done=int(task_rows["done"]),
    )

    # --- assignments
    counts = {"todo": 0, "in_progress": 0, "done": 0}
    overdue = 0
    upcoming: list[Any] = []
    deadlines: list[Deadline] = []
    for a in assignment_rows:
        counts[a["status"]] = counts.get(a["status"], 0) + 1
        due: datetime | None = a["due_at"]
        if a["status"] == "done" or due is None:
            continue
        if due < now:
            overdue += 1
        else:
            upcoming.append(a)
        deadlines.append(Deadline("assignment", str(a["id"]), a["title"], _days_left(due, tz, today)))
    upcoming.sort(key=lambda a: a["due_at"])
    next_due = upcoming[0] if upcoming else None
    for exam in overview.exams:
        deadlines.append(Deadline("exam", str(exam.id), exam.title, exam.days_left))

    # --- what to do next
    weak = [
        WeakTopic(
            name=d.filename, accuracy=d.accuracy or 0.0, answers=d.answers,
            material_id=str(d.material_id) if d.material_id else None,
        )
        for d in progress.documents
        if d.weak
    ]
    recommendations = recommend_next(
        Signals(
            weak_topics=weak, revision_due=int(cards["due"]), deadlines=deadlines,
            failed_materials=figures.documents_failed, ready_materials=figures.documents_ready,
            materials=figures.documents, quiz_attempts=figures.quiz_attempts,
        )
    )

    return CourseAnalytics(
        attempts=attempts,
        trend=trend,
        by_type=by_type,
        weeks=week_points,
        coverage=CoverageOut(
            documents=coverage.documents, documents_ready=coverage.documents_ready,
            documents_practised=coverage.documents_practised,
            practised_share=share(coverage.documents_practised, coverage.documents_ready),
            modules_with_files=coverage.modules_with_files, modules_practised=coverage.modules_practised,
        ),
        progress=course_progress(inputs),
        progress_parts=[ProgressPartOut(key=p.key, value=p.value, weight=p.weight) for p in progress_parts(inputs)],
        assignments=AssignmentFigures(
            todo=counts["todo"], in_progress=counts["in_progress"], done=counts["done"], overdue=overdue,
            next_due_at=next_due["due_at"] if next_due else None,
            next_due_title=next_due["title"] if next_due else None,
        ),
        revision=RevisionFigures(cards=int(cards["cards"]), due=int(cards["due"])),
        recommendations=[
            RecommendationOut(kind=r.kind, priority=r.priority, ref_id=r.ref_id, label=r.label, params=r.params)
            for r in recommendations
        ],
    )


def _days_left(due: datetime, tz: str, today: date) -> int:
    """Days from the student's today to the day `due` falls on in their time zone."""
    try:
        zone = ZoneInfo(tz)
    except Exception:  # an unknown zone name falls back to UTC rather than failing the page
        zone = ZoneInfo("UTC")
    return (due.astimezone(zone).date() - today).days


# ------------------------------------------------------------------------------ assignments


@router.get("/subjects/{subject_id}/assignments", response_model=list[AssignmentOut])
async def course_assignments(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> list[AssignmentOut]:
    """The assignments of this course: open ones first, by due date."""
    async with db.session() as session:
        await _require_course(session, subject_id)
        rows = (
            (
                await session.execute(
                    text(
                        f"{_LIST_SQL} WHERE a.subject_id = :id ORDER BY (a.status = 'done'), "
                        "a.due_at NULLS LAST, a.created_at DESC LIMIT 200"
                    ),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
    return [_out(r) for r in rows]


# ------------------------------------------------------------------------------ modules


@router.post("/subjects/{subject_id}/modules/rename", response_model=ModuleRenameOut)
async def rename_module(
    subject_id: UUID, body: ModuleRenameIn, _user: AuthUser, db: UserDbDep
) -> ModuleRenameOut:
    """Rename a module (every file labelled with it), merge it into another, or empty it
    (`new` blank: the files stay but belong to no module). With `old` null, the files that are in
    no module are put into `new`. Names that differ only in case or spacing are the same module."""
    try:
        old = clean_optional_label(body.old)
        new = clean_optional_label(body.new)
    except ValueError as exc:
        raise AppError(422, "invalid_module", str(exc)) from exc
    if old is None and new is None:
        raise AppError(422, "invalid_module", "Say which module to change.")
    if old is not None and new is not None and name_key(old) == name_key(new) and old == new:
        raise AppError(422, "invalid_module", "The new name is the same as the old one.")

    where = "module IS NULL" if old is None else "lower(regexp_replace(btrim(module), '\\s+', ' ', 'g')) = :key"
    async with db.session() as session:
        await _require_course(session, subject_id)
        result = await session.execute(
            text(
                f"UPDATE materials SET module = :new, updated_at = now() WHERE subject_id = :id "
                f"AND deleted_at IS NULL AND {where}"
            ),
            {"new": new, "id": subject_id, "key": name_key(old) if old is not None else None},
        )
        updated = result.rowcount or 0  # type: ignore[attr-defined]
    return ModuleRenameOut(updated=updated)
