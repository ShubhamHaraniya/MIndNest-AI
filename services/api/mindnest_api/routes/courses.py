"""Course figures for the Subjects pages: one table row per course, one workspace per course.

The plain /subjects routes stay the place to create, edit, archive and delete a subject. These
routes only read, and put the numbers a student wants next to a course (documents ready, past
papers, quiz average, next exam, last activity) in a single request instead of one per course.

Topic progress is worked out from the student's own quiz answers: every question remembers the
file it was written from (`quiz_questions.source->>'filename'`), so accuracy can be shown per
document and, through the document's module label, per module. The unused `topics` table is not
involved. Everything runs inside `db.session()`, so row-level security limits it to the signed-in
student, and a course that belongs to someone else answers 404.
"""

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from mindnest_core.plannerlogic import local_today
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.dashboard import WEAK_BELOW, WEAK_MIN_ANSWERS
from mindnest_api.routes.subjects import _like_pattern

router = APIRouter(tags=["courses"])

MAX_COURSES = 200
UPCOMING_EXAMS = 5


class CourseFigures(BaseModel):
    id: UUID
    name: str
    course_code: str | None
    semester: str | None
    description: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    documents: int
    documents_ready: int
    documents_working: int  # waiting to start or being read
    documents_failed: int
    past_papers: int
    notes: int
    quizzes: int  # quizzes written for this course (ready ones)
    quiz_attempts: int  # completed attempts
    quiz_average: float | None  # 0..1, points over total across completed attempts
    chats: int
    next_exam_title: str | None
    next_exam_on: date | None
    next_exam_days: int | None
    last_activity_at: datetime | None


class CoursePage(BaseModel):
    items: list[CourseFigures]
    total: int


class ExamBrief(BaseModel):
    id: UUID
    title: str
    exam_on: date
    days_left: int


class CourseOverview(BaseModel):
    course: CourseFigures
    exams: list[ExamBrief]


class ProgressSummary(BaseModel):
    answers: int
    accuracy: float | None  # 0..1
    attempts: int
    last_practised_at: datetime | None
    weak_documents: int


class ModuleProgress(BaseModel):
    module: str | None  # None = files not placed in a module
    documents: int
    documents_ready: int
    past_papers: int
    notes: int
    answers: int
    accuracy: float | None  # 0..1, None until a quiz answer from this module is marked
    last_practised_at: datetime | None
    weak: bool


class DocumentProgress(BaseModel):
    material_id: UUID | None  # None: quiz answers cite a file that has since been deleted
    filename: str
    kind: str | None
    module: str | None
    status: str | None
    answers: int
    accuracy: float | None  # 0..1
    last_practised_at: datetime | None
    weak: bool


class CourseProgress(BaseModel):
    summary: ProgressSummary
    modules: list[ModuleProgress]
    documents: list[DocumentProgress]


# One row per course. The sub-selects are the same ones the dashboard uses for its course strip.
_FIGURES = """
  SELECT s.id, s.name, s.course_code, s.semester, s.description, s.archived_at, s.created_at,
    s.updated_at,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL) AS documents,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
       AND m.status = 'ready') AS documents_ready,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
       AND m.status IN ('uploaded', 'processing')) AS documents_working,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
       AND m.status = 'failed') AS documents_failed,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
       AND m.kind = 'past_paper') AS past_papers,
    (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
       AND m.kind = 'note') AS notes,
    (SELECT count(*) FROM quizzes z WHERE z.subject_id = s.id AND z.status = 'ready') AS quizzes,
    (SELECT count(*) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
       WHERE z.subject_id = s.id AND t.status = 'completed' AND t.total > 0) AS quiz_attempts,
    (SELECT sum(t.points) / NULLIF(sum(t.total), 0) FROM quiz_attempts t
       JOIN quizzes z ON z.id = t.quiz_id
       WHERE z.subject_id = s.id AND t.status = 'completed' AND t.total > 0) AS quiz_average,
    (SELECT count(*) FROM conversations c WHERE c.subject_id = s.id) AS chats,
    ex.title AS next_exam_title, ex.exam_on AS next_exam_on,
    GREATEST(
      s.updated_at,
      COALESCE((SELECT max(c.updated_at) FROM conversations c WHERE c.subject_id = s.id), 'epoch'),
      COALESCE((SELECT max(COALESCE(m.last_opened_at, m.created_at)) FROM materials m
                 WHERE m.subject_id = s.id AND m.deleted_at IS NULL), 'epoch'),
      COALESCE((SELECT max(t.finished_at) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                 WHERE z.subject_id = s.id), 'epoch')
    ) AS last_activity_at
  FROM subjects s
  LEFT JOIN LATERAL (
    SELECT e.title, e.exam_on FROM exams e
    WHERE e.subject_id = s.id AND e.exam_on >= :today ORDER BY e.exam_on LIMIT 1
  ) ex ON true
"""


def _figures(row: Any, today: date) -> CourseFigures:
    exam_on: date | None = row["next_exam_on"]
    average = row["quiz_average"]
    return CourseFigures(
        id=row["id"], name=row["name"], course_code=row["course_code"], semester=row["semester"],
        description=row["description"], archived_at=row["archived_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        documents=row["documents"], documents_ready=row["documents_ready"],
        documents_working=row["documents_working"], documents_failed=row["documents_failed"],
        past_papers=row["past_papers"], notes=row["notes"], quizzes=row["quizzes"],
        quiz_attempts=row["quiz_attempts"],
        quiz_average=round(float(average), 4) if average is not None else None,
        chats=row["chats"], next_exam_title=row["next_exam_title"], next_exam_on=exam_on,
        next_exam_days=(exam_on - today).days if exam_on else None,
        last_activity_at=row["last_activity_at"],
    )


async def _require_course(session: AsyncSession, subject_id: UUID) -> None:
    found = (
        await session.execute(text("SELECT 1 FROM subjects WHERE id = :id"), {"id": subject_id})
    ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Subject not found.")


@router.get("/courses", response_model=CoursePage)
async def list_courses(
    user: AuthUser,
    db: UserDbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    state: Literal["active", "archived", "all"] = "active",
) -> CoursePage:
    """Every course with its figures, newest activity first. Same filters as GET /subjects."""
    today = local_today(user.timezone, datetime.now(UTC))
    conditions: list[str] = []
    params: dict[str, Any] = {"today": today, "limit": MAX_COURSES}
    if state == "active":
        conditions.append("s.archived_at IS NULL")
    elif state == "archived":
        conditions.append("s.archived_at IS NOT NULL")
    if q and q.strip():
        conditions.append(r"(s.name ILIKE :q ESCAPE '\' OR s.course_code ILIKE :q ESCAPE '\')")
        params["q"] = _like_pattern(q.strip())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(f"{_FIGURES} {where} ORDER BY last_activity_at DESC, s.id LIMIT :limit"),
                    params,
                )
            )
            .mappings()
            .all()
        )
    items = [_figures(row, today) for row in rows]
    return CoursePage(items=items, total=len(items))


@router.get("/subjects/{subject_id}/overview", response_model=CourseOverview)
async def course_overview(subject_id: UUID, user: AuthUser, db: UserDbDep) -> CourseOverview:
    """The figures for one course plus its upcoming exams: what the workspace header shows."""
    today = local_today(user.timezone, datetime.now(UTC))
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(f"{_FIGURES} WHERE s.id = :id"), {"id": subject_id, "today": today}
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AppError(404, "not_found", "Subject not found.")
        exams = (
            (
                await session.execute(
                    text(
                        "SELECT id, title, exam_on FROM exams WHERE subject_id = :id "
                        "AND exam_on >= :today ORDER BY exam_on LIMIT :n"
                    ),
                    {"id": subject_id, "today": today, "n": UPCOMING_EXAMS},
                )
            )
            .mappings()
            .all()
        )
    return CourseOverview(
        course=_figures(row, today),
        exams=[
            ExamBrief(id=e["id"], title=e["title"], exam_on=e["exam_on"], days_left=(e["exam_on"] - today).days)
            for e in exams
        ],
    )


def _natural_key(module: str) -> list[Any]:
    """"Unit 2" before "Unit 10": digits compare as numbers."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", module)]


def _accuracy(score: float, answers: int) -> float | None:
    return round(score / answers, 4) if answers else None


def _is_weak(score: float, answers: int) -> bool:
    return answers >= WEAK_MIN_ANSWERS and score / answers < WEAK_BELOW


@router.get("/subjects/{subject_id}/progress", response_model=CourseProgress)
async def course_progress(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> CourseProgress:
    """Accuracy per source document and per module, from the marked quiz answers of this course.

    A document counts as weak under the same rule as the dashboard (fewer than 80% over at least
    three answers). Documents never practised are listed with zero answers so the student can see
    what has not been tried yet."""
    async with db.session() as session:
        await _require_course(session, subject_id)
        materials = (
            (
                await session.execute(
                    text(
                        "SELECT id, filename, kind, module, status FROM materials "
                        "WHERE subject_id = :id AND deleted_at IS NULL ORDER BY created_at DESC, id"
                    ),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
        answered = (
            (
                await session.execute(
                    text(
                        "SELECT q.source->>'filename' AS filename, count(*) AS answers, "
                        "sum(a.score) AS score, max(COALESCE(t.finished_at, t.submitted_at)) AS last "
                        "FROM quiz_answers a JOIN quiz_questions q ON q.id = a.question_id "
                        "JOIN quiz_attempts t ON t.id = a.attempt_id JOIN quizzes z ON z.id = q.quiz_id "
                        "WHERE z.subject_id = :id AND a.score IS NOT NULL AND t.status = 'completed' "
                        "AND q.source->>'filename' IS NOT NULL GROUP BY q.source->>'filename'"
                    ),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
        attempts = (
            await session.execute(
                text(
                    "SELECT count(*) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id "
                    "WHERE z.subject_id = :id AND t.status = 'completed' AND t.total > 0"
                ),
                {"id": subject_id},
            )
        ).scalar_one()

    by_name = {r["filename"]: r for r in answered}
    claimed: set[str] = set()  # two files can share a name: the newest one takes the answers
    documents: list[DocumentProgress] = []
    # Modules are rolled up from the documents that are still in the course: (row, answers, score).
    grouped: dict[str | None, list[tuple[Any, int, float]]] = {}
    for m in materials:
        hit = by_name.get(m["filename"]) if m["filename"] not in claimed else None
        if hit is not None:
            claimed.add(m["filename"])
        answers = int(hit["answers"]) if hit else 0
        score = float(hit["score"]) if hit else 0.0
        grouped.setdefault(m["module"], []).append((m, answers, score))
        documents.append(
            DocumentProgress(
                material_id=m["id"], filename=m["filename"], kind=m["kind"], module=m["module"],
                status=m["status"], answers=answers, accuracy=_accuracy(score, answers),
                last_practised_at=hit["last"] if hit else None, weak=_is_weak(score, answers),
            )
        )
    for name, hit in by_name.items():
        if name in claimed:
            continue
        answers, score = int(hit["answers"]), float(hit["score"])
        documents.append(
            DocumentProgress(
                material_id=None, filename=name, kind=None, module=None, status=None,
                answers=answers, accuracy=_accuracy(score, answers), last_practised_at=hit["last"],
                weak=_is_weak(score, answers),
            )
        )

    last_by_doc = {d.material_id: d.last_practised_at for d in documents if d.material_id}
    modules: list[ModuleProgress] = []
    for name, members in grouped.items():
        answers = sum(n for _, n, _ in members)
        score = sum(sc for _, _, sc in members)
        lasts = [last for m, _, _ in members if (last := last_by_doc.get(m["id"]))]
        modules.append(
            ModuleProgress(
                module=name, documents=len(members),
                documents_ready=sum(1 for m, _, _ in members if m["status"] == "ready"),
                past_papers=sum(1 for m, _, _ in members if m["kind"] == "past_paper"),
                notes=sum(1 for m, _, _ in members if m["kind"] == "note"),
                answers=answers, accuracy=_accuracy(score, answers),
                last_practised_at=max(lasts) if lasts else None, weak=_is_weak(score, answers),
            )
        )
    modules.sort(key=lambda mod: (mod.module is None, _natural_key(mod.module or "")))

    total_answers = sum(int(r["answers"]) for r in answered)
    total_score = sum(float(r["score"]) for r in answered)
    last_all = [r["last"] for r in answered if r["last"]]
    return CourseProgress(
        summary=ProgressSummary(
            answers=total_answers, accuracy=_accuracy(total_score, total_answers),
            attempts=int(attempts), last_practised_at=max(last_all) if last_all else None,
            weak_documents=sum(1 for d in documents if d.weak),
        ),
        modules=modules,
        documents=documents,
    )
