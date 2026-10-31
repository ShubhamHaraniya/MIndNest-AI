"""Everything the dashboard shows, in one request, worked out from the student's own data.

How each number is defined (windows, which statuses count, what a weak topic is, how tasks are
classed) lives in `mindnest_core.dashlogic`, so this page, the Quizzes, Subjects, planner and
calendar pages agree. This module only asks the database and assembles the answer.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from mindnest_core import dashlogic as dl
from mindnest_core.dashlogic import (  # noqa: F401  (WEAK_* and streak are re-exported for importers)
    WEAK_BELOW,
    WEAK_MIN_ANSWERS,
    WEEK_DAYS,
    SetupFacts,
    TaskRow,
    streak,
)
from mindnest_core.db import as_json
from mindnest_core.plannerlogic import local_today, local_zone
from mindnest_core.quizstore import CARD_DUE_SQL
from pydantic import BaseModel
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep

router = APIRouter(tags=["dashboard"])

MAX_SCHEDULE = 40
MAX_OVERDUE_SHOWN = 8


class DashStats(BaseModel):
    subjects: int
    materials: int
    materials_ready: int
    quiz_attempts: int
    quiz_average: float | None  # 0..1
    revision_due: int
    conversations: int


class TodayTasks(BaseModel):
    total: int
    done: int
    minutes_total: int
    minutes_done: int


class DashSubject(BaseModel):
    id: UUID
    name: str
    course_code: str | None
    semester: str | None
    materials: int
    materials_ready: int
    quiz_attempts: int
    quiz_average: float | None  # 0..1


class StudyDay(BaseModel):
    date: date
    minutes_done: int
    minutes_planned: int


class TrendPoint(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    title: str
    percent: float  # 0..1
    finished_at: datetime | None
    href: str = ""


class WeakTopic(BaseModel):
    subject_id: UUID
    subject_name: str
    material: str
    accuracy: float  # 0..1
    answers: int
    material_id: UUID | None = None
    href: str = ""


class Deadline(BaseModel):
    kind: str  # "exam" | "assignment"
    id: UUID
    title: str
    subject_name: str | None
    on: date
    days_left: int  # negative = overdue
    href: str = ""


class RecentChat(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    href: str = ""


class Course(BaseModel):
    id: UUID
    name: str
    course_code: str | None
    semester: str | None
    documents: int
    documents_ready: int
    past_papers: int
    notes: int
    quiz_attempts: int
    quiz_average: float | None  # 0..1
    last_activity_at: datetime | None
    next_exam_title: str | None
    next_exam_on: date | None
    next_exam_days: int | None
    chats: int


class Overview(BaseModel):
    """The figures of whatever the dashboard is scoped to (one course, or every course)."""

    courses: int  # active courses the figures cover (1 when a course is chosen)
    documents: int
    documents_ready: int
    past_papers: int
    notes: int
    quiz_attempts: int
    quiz_average: float | None  # 0..1
    chats: int
    last_activity_at: datetime | None
    next_exam_title: str | None
    next_exam_on: date | None
    next_exam_days: int | None


class ScheduleTask(BaseModel):
    id: UUID
    title: str
    minutes: int
    status: str  # todo | done | skipped | cancelled (as stored)
    kind: str
    subject_id: UUID | None
    subject_name: str | None
    # Added so the dashboard shows what the planner shows.
    state: str = "pending"  # pending | completed | overdue | cancelled (taskstate.task_state)
    planned_for: date | None = None
    template: str | None = None
    params: dict[str, Any] = {}
    source: str = "manual"
    href: str = ""


class WeekMarker(BaseModel):
    kind: str  # "exam" | "assignment"
    title: str
    href: str = ""


class WeekDay(BaseModel):
    date: date
    minutes_planned: int
    minutes_done: int
    tasks: int
    day_off: bool
    markers: list[WeekMarker]
    href: str = ""


class RecentDocument(BaseModel):
    id: UUID
    filename: str
    kind: str
    status: str
    subject_id: UUID
    subject_name: str
    module: str | None
    at: datetime
    reason: str  # "opened" | "added"
    href: str = ""


class AssignmentDue(BaseModel):
    id: UUID
    title: str
    subject_name: str | None
    status: str
    due_on: date
    days_left: int  # negative = overdue
    href: str = ""


class ActivityItem(BaseModel):
    kind: str  # chat | quiz | material | task | assignment
    title: str
    detail: str | None
    subject_name: str | None
    at: datetime
    href: str


class SetupStepOut(BaseModel):
    key: str  # course | material | institution | provider | chat | quiz
    done: bool
    href: str


class Setup(BaseModel):
    show: bool  # true while one of the four basics (course, material, institution, key) is open
    done: int
    total: int
    steps: list[SetupStepOut]


class DashboardOut(BaseModel):
    course: Course | None
    daily_minutes: int
    schedule: list[ScheduleTask]
    week: list[WeekDay]
    recent_documents: list[RecentDocument]
    assignments_due: list[AssignmentDue]
    activity: list[ActivityItem]
    today: date
    stats: DashStats
    streak_days: int
    today_tasks: TodayTasks
    subjects: list[DashSubject]
    study_week: list[StudyDay]
    quiz_trend: list[TrendPoint]
    weak_topics: list[WeakTopic]
    deadlines: list[Deadline]
    recent_chats: list[RecentChat]
    # "course" when a valid course was asked for, otherwise "all" (the same default as chat and quizzes).
    scope: str = "all"
    overview: Overview | None = None
    # Tasks in the schedule by shared state: pending, completed, overdue, cancelled.
    task_states: dict[str, int] = {}
    setup: Setup | None = None


def _scoped(column: str) -> str:
    """SQL condition that keeps a row when no course is chosen or when it belongs to the course."""
    return f"(CAST(:sc AS uuid) IS NULL OR {column} = CAST(:sc AS uuid))"


def _task_row(r: Any) -> TaskRow:
    return TaskRow(
        id=r["id"], title=r["title"], planned_for=r["planned_for"], minutes=int(r["minutes"]),
        status=r["status"], kind=r["kind"], source=r["source"], template=r["template"],
        params=as_json(r["params"]) or {}, subject_id=r["subject_id"], subject_name=r["subject"],
        assignment_id=r["assignment_id"], exam_id=r["exam_id"],
    )


def _schedule_out(row: TaskRow, today: date) -> ScheduleTask:
    return ScheduleTask(
        id=row.id, title=row.title, minutes=row.minutes, status=row.status, kind=row.kind,
        subject_id=row.subject_id, subject_name=row.subject_name, state=dl.state_of(row, today),
        planned_for=row.planned_for, template=row.template, params=row.params or {},
        source=row.source, href=dl.task_href(row),
    )


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    user: AuthUser, db: UserDbDep, course: Annotated[UUID | None, Query()] = None
) -> DashboardOut:
    today = local_today(user.timezone, datetime.now(UTC))
    tz = local_zone(user.timezone).key
    async with db.session() as session:

        async def rows(sql: str, **params: Any) -> list[Any]:
            return list((await session.execute(text(sql), params)).mappings().all())

        # ---- which course (if any) the page is about ---------------------------------------
        course_rows = await rows(
            """
            SELECT s.id, s.name, s.course_code, s.semester,
              GREATEST(
                s.updated_at,
                COALESCE((SELECT max(c.updated_at) FROM conversations c WHERE c.subject_id = s.id), 'epoch'),
                COALESCE((SELECT max(COALESCE(m.last_opened_at, m.created_at)) FROM materials m
                           WHERE m.subject_id = s.id AND m.deleted_at IS NULL), 'epoch'),
                COALESCE((SELECT max(t.finished_at) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                           WHERE z.subject_id = s.id), 'epoch')
              ) AS last_activity
            FROM subjects s WHERE s.archived_at IS NULL ORDER BY last_activity DESC, s.created_at DESC
            """
        )
        # No fallback to "the most recent course": without a (valid) choice the page is about all
        # courses, which is also what chat and quizzes do.
        chosen = next((r for r in course_rows if r["id"] == course), None)
        sc = str(chosen["id"]) if chosen is not None else None

        # ---- the content figures: one query, scoped, feeds both `stats` and `overview` -------
        figures = (
            await rows(
                f"""
                SELECT
                  (SELECT count(*) FROM subjects WHERE archived_at IS NULL) AS courses,
                  (SELECT count(*) FROM materials m JOIN subjects s ON s.id = m.subject_id
                     WHERE m.deleted_at IS NULL AND s.archived_at IS NULL AND {_scoped("m.subject_id")}) AS docs,
                  (SELECT count(*) FROM materials m JOIN subjects s ON s.id = m.subject_id
                     WHERE m.deleted_at IS NULL AND s.archived_at IS NULL AND m.status = 'ready'
                       AND {_scoped("m.subject_id")}) AS ready,
                  (SELECT count(*) FROM materials m JOIN subjects s ON s.id = m.subject_id
                     WHERE m.deleted_at IS NULL AND s.archived_at IS NULL AND m.kind = 'past_paper'
                       AND {_scoped("m.subject_id")}) AS papers,
                  (SELECT count(*) FROM materials m JOIN subjects s ON s.id = m.subject_id
                     WHERE m.deleted_at IS NULL AND s.archived_at IS NULL AND m.kind = 'note'
                       AND {_scoped("m.subject_id")}) AS notes,
                  (SELECT count(*) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                     WHERE t.status = 'completed' AND t.total > 0 AND {_scoped("z.subject_id")}) AS attempts,
                  (SELECT sum(t.points) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                     WHERE t.status = 'completed' AND t.total > 0 AND {_scoped("z.subject_id")}) AS points,
                  (SELECT sum(t.total) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                     WHERE t.status = 'completed' AND t.total > 0 AND {_scoped("z.subject_id")}) AS total,
                  (SELECT count(*) FROM revision_cards c
                     WHERE {CARD_DUE_SQL} AND {_scoped("c.subject_id")}) AS due,
                  (SELECT count(*) FROM conversations c WHERE {_scoped("c.subject_id")}) AS chats
                """,
                sc=sc, tz=tz,
            )
        )[0]
        quiz_average = dl.average(figures["points"], figures["total"])

        exam = await rows(
            f"SELECT title, exam_on FROM exams WHERE exam_on >= :d AND {_scoped('subject_id')} "
            "ORDER BY exam_on, created_at LIMIT 1",
            d=today, sc=sc,
        )
        last_activity = chosen["last_activity"] if chosen is not None else (
            max((r["last_activity"] for r in course_rows), default=None)
        )
        if last_activity is not None and last_activity.year <= 1971:
            last_activity = None

        overview = Overview(
            courses=1 if chosen is not None else int(figures["courses"]),
            documents=figures["docs"], documents_ready=figures["ready"],
            past_papers=figures["papers"], notes=figures["notes"],
            quiz_attempts=figures["attempts"], quiz_average=quiz_average, chats=figures["chats"],
            last_activity_at=last_activity,
            next_exam_title=exam[0]["title"] if exam else None,
            next_exam_on=exam[0]["exam_on"] if exam else None,
            next_exam_days=dl.days_left(exam[0]["exam_on"], today) if exam else None,
        )
        course_out: Course | None = None
        if chosen is not None:
            course_out = Course(
                id=chosen["id"], name=chosen["name"], course_code=chosen["course_code"],
                semester=chosen["semester"], documents=overview.documents,
                documents_ready=overview.documents_ready, past_papers=overview.past_papers,
                notes=overview.notes, quiz_attempts=overview.quiz_attempts,
                quiz_average=overview.quiz_average, last_activity_at=overview.last_activity_at,
                next_exam_title=overview.next_exam_title, next_exam_on=overview.next_exam_on,
                next_exam_days=overview.next_exam_days, chats=overview.chats,
            )

        # ---- the student's day: tasks, planned minutes, the streak (never scoped by course) ---
        overdue_first, _ = dl.overdue_task_window(today)
        week_start = today - timedelta(days=WEEK_DAYS - 1)
        ahead_end = today + timedelta(days=WEEK_DAYS - 1)
        task_rows = dl.dedupe_tasks(
            _task_row(r)
            for r in await rows(
                "SELECT k.id, k.title, k.planned_for, k.minutes, k.status, k.kind, k.source, k.template, "
                "k.params, k.subject_id, s.name AS subject, k.assignment_id, k.exam_id "
                "FROM study_tasks k LEFT JOIN subjects s ON s.id = k.subject_id "
                "WHERE k.planned_for BETWEEN :a AND :b ORDER BY k.planned_for, k.created_at, k.id",
                a=min(overdue_first, week_start), b=ahead_end,
            )
        )
        by_day: dict[date, list[TaskRow]] = {}
        for task in task_rows:
            by_day.setdefault(task.planned_for, []).append(task)

        today_rows = by_day.get(today, [])
        today_sum = dl.summarise_tasks(today_rows, today)
        overdue_rows = [
            r for r in task_rows if r.planned_for < today and dl.state_of(r, today) == "overdue"
        ]
        schedule_rows = dl.order_tasks(overdue_rows[:MAX_OVERDUE_SHOWN] + today_rows, today)[:MAX_SCHEDULE]
        task_states = dl.counts_by_state(overdue_rows + today_rows, today)

        study_week = []
        for i in range(WEEK_DAYS):
            d = week_start + timedelta(days=i)
            summary = dl.summarise_tasks(by_day.get(d, []), today)
            study_week.append(
                StudyDay(date=d, minutes_done=summary.minutes_done, minutes_planned=summary.minutes_total)
            )

        active: set[date] = {
            r["d"]
            for r in await rows(
                "SELECT COALESCE((completed_at AT TIME ZONE :tz)::date, planned_for) AS d FROM study_tasks "
                "WHERE status = 'done' AND COALESCE((completed_at AT TIME ZONE :tz)::date, planned_for) >= :a "
                "UNION SELECT (finished_at AT TIME ZONE :tz)::date FROM quiz_attempts "
                "WHERE status = 'completed' AND finished_at IS NOT NULL "
                "AND (finished_at AT TIME ZONE :tz)::date >= :a",
                a=today - timedelta(days=dl.STREAK_LOOKBACK_DAYS), tz=tz,
            )
        }

        preferences = await rows("SELECT daily_minutes, days_off FROM study_preferences")
        daily_minutes = int(preferences[0]["daily_minutes"]) if preferences else 90
        days_off = set(preferences[0]["days_off"]) if preferences else set()

        # ---- courses, quizzes, weak topics --------------------------------------------------
        subject_rows = await rows(
            """
            SELECT s.id, s.name, s.course_code, s.semester,
              (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL) AS materials,
              (SELECT count(*) FROM materials m WHERE m.subject_id = s.id AND m.deleted_at IS NULL
                 AND m.status = 'ready') AS ready,
              (SELECT count(*) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                 WHERE z.subject_id = s.id AND t.status = 'completed' AND t.total > 0) AS attempts,
              (SELECT sum(t.points) / NULLIF(sum(t.total), 0) FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                 WHERE z.subject_id = s.id AND t.status = 'completed' AND t.total > 0) AS average
            FROM subjects s WHERE s.archived_at IS NULL ORDER BY s.updated_at DESC LIMIT 6
            """
        )

        trend_rows = await rows(
            "SELECT t.id, t.quiz_id, z.title, t.points, t.total, t.finished_at FROM quiz_attempts t "
            f"JOIN quizzes z ON z.id = t.quiz_id WHERE t.status = 'completed' AND t.total > 0 "
            f"AND {_scoped('z.subject_id')} ORDER BY t.finished_at DESC NULLS LAST LIMIT 10",
            sc=sc,
        )

        weak_rows = await rows(
            "SELECT w.*, (SELECT m.id FROM materials m WHERE m.subject_id = w.subject_id "
            "AND m.filename = w.material AND m.deleted_at IS NULL ORDER BY m.created_at DESC LIMIT 1) "
            "AS material_id FROM ("
            "SELECT z.subject_id, s.name AS subject_name, q.source->>'filename' AS material, "
            "avg(a.score) AS acc, count(*) AS n FROM quiz_answers a "
            "JOIN quiz_questions q ON q.id = a.question_id JOIN quiz_attempts t ON t.id = a.attempt_id "
            "JOIN quizzes z ON z.id = q.quiz_id JOIN subjects s ON s.id = z.subject_id "
            "WHERE a.score IS NOT NULL AND t.status = 'completed' AND q.source->>'filename' IS NOT NULL "
            f"AND s.archived_at IS NULL AND {_scoped('z.subject_id')} "
            "GROUP BY z.subject_id, s.name, q.source->>'filename' "
            "HAVING count(*) >= :n AND avg(a.score) < :below ORDER BY avg(a.score), count(*) DESC LIMIT 5"
            ") w ORDER BY w.acc, w.n DESC",
            n=dl.WEAK_MIN_ANSWERS, below=dl.WEAK_BELOW, sc=sc,
        )

        # ---- deadlines and assignments ------------------------------------------------------
        deadline_first, deadline_last = dl.deadline_window(today)
        exam_rows = await rows(
            "SELECT e.id, e.title, e.exam_on AS due, s.name AS subject FROM exams e "
            f"LEFT JOIN subjects s ON s.id = e.subject_id WHERE e.exam_on BETWEEN :a AND :b "
            f"AND {_scoped('e.subject_id')}",
            a=today, b=deadline_last, sc=sc,
        )
        assignment_rows = await rows(
            "SELECT a.id, a.title, (a.due_at AT TIME ZONE :tz)::date AS due, s.name AS subject "
            "FROM assignments a LEFT JOIN subjects s ON s.id = a.subject_id "
            "WHERE a.status <> 'done' AND a.due_at IS NOT NULL "
            "AND (a.due_at AT TIME ZONE :tz)::date BETWEEN :a AND :b "
            f"AND {_scoped('a.subject_id')}",
            tz=tz, a=deadline_first, b=deadline_last, sc=sc,
        )
        panel_first, panel_last = dl.assignment_window(today)
        due_rows = await rows(
            "SELECT a.id, a.title, a.status, (a.due_at AT TIME ZONE :tz)::date AS due, s.name AS subject "
            "FROM assignments a LEFT JOIN subjects s ON s.id = a.subject_id "
            "WHERE a.status <> 'done' AND a.due_at IS NOT NULL "
            "AND (a.due_at AT TIME ZONE :tz)::date BETWEEN :a AND :b "
            f"AND {_scoped('a.subject_id')} ORDER BY a.due_at LIMIT 8",
            tz=tz, a=panel_first, b=panel_last, sc=sc,
        )

        # The week ahead is part of the student's day, so like the planner it is not scoped.
        ahead_exams = await rows(
            "SELECT id, title, exam_on AS d FROM exams WHERE exam_on BETWEEN :a AND :b", a=today, b=ahead_end
        )
        ahead_assignments = await rows(
            "SELECT id, title, (due_at AT TIME ZONE :tz)::date AS d FROM assignments WHERE status <> 'done' "
            "AND due_at IS NOT NULL AND (due_at AT TIME ZONE :tz)::date BETWEEN :a AND :b",
            tz=tz, a=today, b=ahead_end,
        )

        # ---- documents, activity, chats -----------------------------------------------------
        document_rows = await rows(
            "SELECT m.id, m.filename, m.kind, m.status, m.subject_id, s.name AS subject, m.module, "
            "COALESCE(m.last_opened_at, m.created_at) AS at, "
            "(CASE WHEN m.last_opened_at IS NULL THEN 'added' ELSE 'opened' END) AS reason "
            "FROM materials m JOIN subjects s ON s.id = m.subject_id "
            f"WHERE m.deleted_at IS NULL AND s.archived_at IS NULL AND {_scoped('m.subject_id')} "
            "ORDER BY COALESCE(m.last_opened_at, m.created_at) DESC LIMIT 8",
            sc=sc,
        )

        activity_rows = await rows(
            f"""
            SELECT e.kind, e.ref, e.title, e.detail, e.at, e.subject_id, e.day, s.name AS subject FROM (
              SELECT 'chat' AS kind, c.id::text AS ref, c.title, NULL::text AS detail,
                     c.updated_at AS at, c.subject_id, NULL::date AS day FROM conversations c
              UNION ALL
              SELECT 'quiz', t.id::text, z.title, round(100 * t.points / t.total)::int::text,
                     t.finished_at, z.subject_id, NULL::date
                FROM quiz_attempts t JOIN quizzes z ON z.id = t.quiz_id
                WHERE t.status = 'completed' AND t.total > 0 AND t.finished_at IS NOT NULL
              UNION ALL
              SELECT 'material', m.id::text, m.filename, m.kind, m.created_at, m.subject_id, NULL::date
                FROM materials m JOIN subjects ms ON ms.id = m.subject_id
                WHERE m.deleted_at IS NULL AND ms.archived_at IS NULL
              UNION ALL
              SELECT 'task', k.id::text, k.title, k.minutes::text, k.completed_at, k.subject_id, k.planned_for
                FROM study_tasks k WHERE k.status = 'done' AND k.completed_at IS NOT NULL
              UNION ALL
              SELECT 'assignment', a.id::text, a.title, r.kind, r.finished_at, a.subject_id, NULL::date
                FROM assignment_runs r JOIN assignments a ON a.id = r.assignment_id
                WHERE r.status = 'ready' AND r.finished_at IS NOT NULL
            ) e LEFT JOIN subjects s ON s.id = e.subject_id
            WHERE {_scoped("e.subject_id")}
            ORDER BY e.at DESC LIMIT 12
            """,
            sc=sc,
        )

        chat_rows = await rows(
            f"SELECT id, title, updated_at FROM conversations WHERE {_scoped('subject_id')} "
            "ORDER BY updated_at DESC LIMIT 4",
            sc=sc,
        )

        # ---- what a new student still has to do (never scoped: it is about the account) -----
        basics = (
            await rows(
                """
                SELECT
                  (SELECT count(*) FROM subjects WHERE archived_at IS NULL) AS courses,
                  (SELECT count(*) FROM materials m JOIN subjects s ON s.id = m.subject_id
                     WHERE m.deleted_at IS NULL AND s.archived_at IS NULL) AS materials,
                  (SELECT count(*) FROM quiz_attempts WHERE status = 'completed' AND total > 0) AS attempts,
                  (SELECT count(*) FROM conversations) AS chats,
                  (SELECT count(*) FROM provider_keys) AS keys
                """
            )
        )[0]

    steps = dl.setup_steps(
        SetupFacts(
            courses=int(basics["courses"]), materials=int(basics["materials"]),
            quiz_attempts=int(basics["attempts"]), conversations=int(basics["chats"]),
            has_institution=bool((user.institution_name or "").strip()),
            provider_keys=int(basics["keys"]),
            first_course_id=course_rows[0]["id"] if course_rows else None,
        )
    )
    setup = Setup(
        show=dl.needs_setup(steps), done=sum(1 for s in steps if s.done), total=len(steps),
        steps=[SetupStepOut(key=s.key, done=s.done, href=s.href) for s in steps],
    )

    deadlines = sorted(
        [Deadline(kind="exam", id=r["id"], title=r["title"], subject_name=r["subject"], on=r["due"],
                  days_left=dl.days_left(r["due"], today), href=dl.deadline_href("exam", r["id"], r["due"]))
         for r in exam_rows]
        + [Deadline(kind="assignment", id=r["id"], title=r["title"], subject_name=r["subject"], on=r["due"],
                    days_left=dl.days_left(r["due"], today),
                    href=dl.deadline_href("assignment", r["id"], r["due"]))
           for r in assignment_rows],
        key=lambda d: (d.on, d.kind),
    )[:6]

    week = []
    for offset in range(WEEK_DAYS):
        d = today + timedelta(days=offset)
        summary = dl.summarise_tasks(by_day.get(d, []), today)
        week.append(
            WeekDay(
                date=d,
                minutes_planned=summary.minutes_total,
                minutes_done=summary.minutes_done,
                tasks=summary.total,
                day_off=d.weekday() in days_off,
                markers=[WeekMarker(kind="exam", title=r["title"], href=dl.deadline_href("exam", r["id"], d))
                         for r in ahead_exams if r["d"] == d]
                + [WeekMarker(kind="assignment", title=r["title"],
                              href=dl.deadline_href("assignment", r["id"], d))
                   for r in ahead_assignments if r["d"] == d],
                href=dl.planner_href(d),
            )
        )

    return DashboardOut(
        course=course_out,
        daily_minutes=daily_minutes,
        schedule=[_schedule_out(r, today) for r in schedule_rows],
        week=week,
        recent_documents=[
            RecentDocument(id=r["id"], filename=r["filename"], kind=r["kind"], status=r["status"],
                           subject_id=r["subject_id"], subject_name=r["subject"], module=r["module"],
                           at=r["at"], reason=r["reason"],
                           href=dl.course_href(r["subject_id"], doc=r["id"]))
            for r in document_rows
        ],
        assignments_due=[
            AssignmentDue(id=r["id"], title=r["title"], subject_name=r["subject"], status=r["status"],
                          due_on=r["due"], days_left=dl.days_left(r["due"], today),
                          href=dl.assignment_href(r["id"]))
            for r in due_rows
        ],
        activity=[
            ActivityItem(kind=r["kind"], title=r["title"],
                         detail=(f"{r['detail']}%" if r["kind"] == "quiz" else r["detail"]),
                         subject_name=r["subject"], at=r["at"],
                         href=dl.activity_href(r["kind"], r["ref"], subject_id=r["subject_id"], day=r["day"]))
            for r in activity_rows
        ],
        today=today,
        stats=DashStats(
            subjects=int(figures["courses"]), materials=figures["docs"], materials_ready=figures["ready"],
            quiz_attempts=figures["attempts"], quiz_average=quiz_average,
            revision_due=figures["due"], conversations=figures["chats"],
        ),
        streak_days=dl.streak(active, today),
        today_tasks=TodayTasks(
            total=today_sum.total, done=today_sum.done,
            minutes_total=today_sum.minutes_total, minutes_done=today_sum.minutes_done,
        ),
        subjects=[
            DashSubject(
                id=r["id"], name=r["name"], course_code=r["course_code"], semester=r["semester"],
                materials=r["materials"], materials_ready=r["ready"], quiz_attempts=r["attempts"],
                quiz_average=round(float(r["average"]), 4) if r["average"] is not None else None,
            )
            for r in subject_rows
        ],
        study_week=study_week,
        quiz_trend=[
            TrendPoint(attempt_id=r["id"], quiz_id=r["quiz_id"], title=r["title"],
                       percent=dl.average(r["points"], r["total"]) or 0.0, finished_at=r["finished_at"],
                       href=dl.attempt_href(r["id"]))
            for r in reversed(trend_rows)
        ],
        weak_topics=[
            WeakTopic(subject_id=r["subject_id"], subject_name=r["subject_name"], material=r["material"],
                      accuracy=round(float(r["acc"]), 4), answers=int(r["n"]),
                      material_id=r["material_id"],
                      href=dl.weak_topic_href(r["subject_id"], r["material_id"]))
            for r in weak_rows
        ],
        deadlines=deadlines,
        recent_chats=[
            RecentChat(id=r["id"], title=r["title"], updated_at=r["updated_at"], href=dl.chat_href(r["id"]))
            for r in chat_rows
        ],
        scope="course" if chosen is not None else "all",
        overview=overview,
        task_states=task_states,
        setup=setup,
    )
