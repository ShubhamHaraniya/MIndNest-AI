"""Exams, the study planner and the calendar.

Everything is private to the signed-in student (row-level security). Dates are plain calendar
dates in the student's own time zone. The plan is made by fixed rules (see plannerlogic), not by
an AI, so generating it is instant and needs no provider key.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from mindnest_core.db import as_json
from mindnest_core.plannerlogic import (
    DEFAULT_DAILY,
    DEFAULT_HORIZON,
    MAX_DAILY,
    MAX_HORIZON,
    MIN_DAILY,
    MIN_HORIZON,
    AssignmentItem,
    ExamItem,
    WeakSpot,
    build_plan,
    drop_decided,
    find_overloads,
    local_today,
    local_zone,
    task_key,
)
from mindnest_core.quizstore import CARD_LIVE_SQL
from mindnest_core.taskstate import task_state
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.gcal import sync_states

router = APIRouter(tags=["planner"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Notes = Annotated[str, StringConstraints(max_length=1000)]
# "skipped" is the old name of "cancelled"; it is accepted and stored as "cancelled".
TaskStatus = Literal["todo", "done", "cancelled", "skipped"]
MAX_CALENDAR_DAYS = 62
MAX_TASK_RANGE_DAYS = 120


# ------------------------------------------------------------------------------ schemas


class PreferencesIn(BaseModel):
    daily_minutes: int = Field(ge=MIN_DAILY, le=MAX_DAILY)
    days_off: list[int] = Field(default_factory=list, max_length=6)

    @field_validator("days_off")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekday numbers run from 0 (Monday) to 6 (Sunday)")
        return sorted(set(value))


class PreferencesOut(PreferencesIn):
    pass


class ExamIn(BaseModel):
    title: Title
    exam_on: date
    subject_id: UUID | None = None
    notes: Notes = ""


class ExamPatch(BaseModel):
    title: Title | None = None
    exam_on: date | None = None
    subject_id: UUID | None = None
    notes: Notes | None = None


class ExamOut(BaseModel):
    id: UUID
    title: str
    exam_on: date
    subject_id: UUID | None
    subject_name: str | None
    notes: str
    days_left: int


class TaskIn(BaseModel):
    title: Title
    planned_for: date
    minutes: int = Field(default=30, ge=5, le=480)
    subject_id: UUID | None = None


class TaskPatch(BaseModel):
    title: Title | None = None
    planned_for: date | None = None
    minutes: int | None = Field(default=None, ge=5, le=480)
    status: TaskStatus | None = None
    subject_id: UUID | None = None


class TaskOut(BaseModel):
    id: UUID
    kind: str
    source: str
    title: str
    template: str | None
    params: dict[str, Any]
    planned_for: date
    minutes: int
    status: str
    # pending | completed | overdue | cancelled, worked out from the status and the day (taskstate).
    state: str
    # A planner task the student moved or resized: generating the plan again leaves it alone.
    pinned: bool
    subject_id: UUID | None
    subject_name: str | None
    assignment_id: UUID | None
    exam_id: UUID | None


class OverloadOut(BaseModel):
    day: date
    minutes: int
    limit: int
    excess: int
    day_off: bool
    suggested: date | None


class TasksOut(BaseModel):
    today: date
    daily_minutes: int
    days_off: list[int]
    items: list[TaskOut]
    # Days from today on that hold more than the student's daily limit (or work on a day off).
    overload: list[OverloadOut]


class GenerateIn(BaseModel):
    days: int = Field(default=DEFAULT_HORIZON, ge=MIN_HORIZON, le=MAX_HORIZON)


class GenerateOut(BaseModel):
    created: int
    first_day: date
    last_day: date
    # "nothing_to_plan": no exam, dated assignment, due card or weak subject was found.
    # "up_to_date": everything the plan would add is already done, cancelled or moved by the student.
    notice: str | None
    # Tasks in the planned days that were left exactly as they were (the student's own, finished,
    # cancelled or moved ones), and new tasks not added because the student already dealt with them.
    kept: int = 0
    already_handled: int = 0


class CalendarEvent(BaseModel):
    kind: Literal["assignment", "exam", "task", "revision", "event"]
    day: date
    id: UUID | None = None
    title: str = ""
    status: str | None = None
    minutes: int | None = None
    count: int | None = None
    template: str | None = None
    params: dict[str, Any] | None = None
    subject_name: str | None = None
    # What a task belongs to (so the Calendar can tell when it falls after a deadline), who made
    # it, and the exact due time of an assignment. Empty for other kinds of event.
    subject_id: UUID | None = None
    assignment_id: UUID | None = None
    exam_id: UUID | None = None
    source: str | None = None
    due_at: datetime | None = None
    # A task's state (pending | completed | overdue | cancelled).
    state: str | None = None
    # The student's own events: time of day ("" = all day), notes, and whether it goes to Google.
    start_time: str | None = None
    notes: str | None = None
    sync_to_google: bool | None = None
    # On Google Calendar? synced | pending | failed; None when Google is not connected or the
    # item is not meant for it.
    sync: str | None = None


class CalendarOut(BaseModel):
    today: date
    events: list[CalendarEvent]


# ------------------------------------------------------------------------------ helpers


def _today(user: AuthUser) -> date:
    return local_today(user.timezone, datetime.now(UTC))


async def _check_subject(session: AsyncSession, subject_id: UUID | None) -> None:
    if subject_id is None:
        return
    found = (
        await session.execute(
            text("SELECT 1 FROM subjects WHERE id = :s AND archived_at IS NULL"), {"s": subject_id}
        )
    ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Subject not found.")


def _check_range(first: date, last: date, limit: int) -> None:
    if last < first or (last - first).days > limit:
        raise AppError(422, "validation_error", f"Choose a range of at most {limit} days.")


_TASK_SQL = """
  SELECT t.id, t.kind, t.source, t.title, t.template, t.params, t.planned_for, t.minutes, t.status,
         t.pinned, t.subject_id, s.name AS subject_name, t.assignment_id, t.exam_id
  FROM study_tasks t LEFT JOIN subjects s ON s.id = t.subject_id
"""


def _task_out(row: Any, today: date) -> TaskOut:
    return TaskOut(
        id=row["id"], kind=row["kind"], source=row["source"], title=row["title"],
        template=row["template"], params=as_json(row["params"]) or {},
        planned_for=row["planned_for"], minutes=row["minutes"], status=row["status"],
        state=task_state(row["status"], row["planned_for"], today), pinned=row["pinned"],
        subject_id=row["subject_id"], subject_name=row["subject_name"],
        assignment_id=row["assignment_id"], exam_id=row["exam_id"],
    )


async def _task_row(session: AsyncSession, task_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_TASK_SQL} WHERE t.id = :id"), {"id": task_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Task not found.")
    return row


_EXAM_SQL = """
  SELECT e.id, e.title, e.exam_on, e.subject_id, s.name AS subject_name, e.notes
  FROM exams e LEFT JOIN subjects s ON s.id = e.subject_id
"""


def _exam_out(row: Any, today: date) -> ExamOut:
    return ExamOut(
        id=row["id"], title=row["title"], exam_on=row["exam_on"], subject_id=row["subject_id"],
        subject_name=row["subject_name"], notes=row["notes"], days_left=(row["exam_on"] - today).days,
    )


async def _exam_row(session: AsyncSession, exam_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_EXAM_SQL} WHERE e.id = :id"), {"id": exam_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Exam not found.")
    return row


# ------------------------------------------------------------------------------ preferences


@router.get("/planner/preferences", response_model=PreferencesOut)
async def get_preferences(_user: AuthUser, db: UserDbDep) -> PreferencesOut:
    async with db.session() as session:
        row = (
            (await session.execute(text("SELECT daily_minutes, days_off FROM study_preferences")))
            .mappings()
            .first()
        )
    if row is None:
        return PreferencesOut(daily_minutes=DEFAULT_DAILY, days_off=[])
    return PreferencesOut(daily_minutes=row["daily_minutes"], days_off=list(row["days_off"]))


@router.put("/planner/preferences", response_model=PreferencesOut)
async def put_preferences(body: PreferencesIn, user: AuthUser, db: UserDbDep) -> PreferencesOut:
    async with db.session() as session:
        await session.execute(
            text(
                "INSERT INTO study_preferences (user_id, daily_minutes, days_off) "
                "VALUES (:u, :m, :d) ON CONFLICT (user_id) DO UPDATE SET "
                "daily_minutes = :m, days_off = :d, updated_at = now()"
            ),
            {"u": user.id, "m": body.daily_minutes, "d": body.days_off},
        )
    return PreferencesOut(daily_minutes=body.daily_minutes, days_off=body.days_off)


# ------------------------------------------------------------------------------ exams


@router.get("/exams", response_model=list[ExamOut])
async def list_exams(user: AuthUser, db: UserDbDep) -> list[ExamOut]:
    today = _today(user)
    async with db.session() as session:
        rows = (
            (await session.execute(text(f"{_EXAM_SQL} ORDER BY e.exam_on, e.created_at LIMIT 200")))
            .mappings()
            .all()
        )
    return [_exam_out(r, today) for r in rows]


@router.post("/exams", status_code=201, response_model=ExamOut)
async def create_exam(body: ExamIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> ExamOut:
    await limiter.check(f"exam-create:{user.id}", 60, 3600)
    async with db.session() as session:
        await _check_subject(session, body.subject_id)
        exam_id = (
            await session.execute(
                text(
                    "INSERT INTO exams (user_id, subject_id, title, exam_on, notes) "
                    "VALUES (:u, :s, :t, :d, :n) RETURNING id"
                ),
                {"u": user.id, "s": body.subject_id, "t": body.title, "d": body.exam_on, "n": body.notes},
            )
        ).scalar_one()
        return _exam_out(await _exam_row(session, exam_id), _today(user))


@router.patch("/exams/{exam_id}", response_model=ExamOut)
async def update_exam(exam_id: UUID, body: ExamPatch, user: AuthUser, db: UserDbDep) -> ExamOut:
    sent = body.model_fields_set
    for name in ("title", "exam_on", "notes"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
    async with db.session() as session:
        await _exam_row(session, exam_id)
        if "subject_id" in changes:
            await _check_subject(session, changes["subject_id"])
        if changes:
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            await session.execute(
                text(f"UPDATE exams SET {sets} WHERE id = :id"), {**changes, "id": exam_id}
            )
        return _exam_out(await _exam_row(session, exam_id), _today(user))


@router.delete("/exams/{exam_id}", status_code=204)
async def delete_exam(exam_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(text("DELETE FROM exams WHERE id = :id"), {"id": exam_id})
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Exam not found.")
    return Response(status_code=204)


# ------------------------------------------------------------------------------ tasks


async def _preferences(session: AsyncSession) -> tuple[int, list[int]]:
    row = (
        (await session.execute(text("SELECT daily_minutes, days_off FROM study_preferences")))
        .mappings()
        .first()
    )
    if row is None:
        return DEFAULT_DAILY, []
    return row["daily_minutes"], list(row["days_off"])


@router.get("/planner/tasks", response_model=TasksOut)
async def list_tasks(
    user: AuthUser,
    db: UserDbDep,
    first: Annotated[date | None, Query(alias="from")] = None,
    last: Annotated[date | None, Query(alias="to")] = None,
) -> TasksOut:
    today = _today(user)
    first = first or today
    last = last or first + timedelta(days=DEFAULT_HORIZON - 1)
    _check_range(first, last, MAX_TASK_RANGE_DAYS)
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"{_TASK_SQL} WHERE t.planned_for BETWEEN :a AND :b "
                        "ORDER BY t.planned_for, (t.status <> 'todo'), t.created_at"
                    ),
                    {"a": first, "b": last},
                )
            )
            .mappings()
            .all()
        )
        daily, days_off = await _preferences(session)
    load: dict[date, int] = {}
    for r in rows:
        if r["status"] in ("todo", "done"):
            load[r["planned_for"]] = load.get(r["planned_for"], 0) + r["minutes"]
    overloads = find_overloads(load, daily_minutes=daily, days_off=days_off, today=today, last=last)
    return TasksOut(
        today=today, daily_minutes=daily, days_off=days_off,
        items=[_task_out(r, today) for r in rows],
        overload=[
            OverloadOut(day=o.day, minutes=o.minutes, limit=o.limit, excess=o.excess,
                        day_off=o.day_off, suggested=o.suggested)
            for o in overloads
        ],
    )


@router.post("/planner/tasks", status_code=201, response_model=TaskOut)
async def create_task(body: TaskIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> TaskOut:
    await limiter.check(f"task-create:{user.id}", 200, 3600)
    async with db.session() as session:
        await _check_subject(session, body.subject_id)
        task_id = (
            await session.execute(
                text(
                    "INSERT INTO study_tasks (user_id, subject_id, kind, source, title, planned_for, minutes) "
                    "VALUES (:u, :s, 'custom', 'manual', :t, :d, :m) RETURNING id"
                ),
                {"u": user.id, "s": body.subject_id, "t": body.title, "d": body.planned_for, "m": body.minutes},
            )
        ).scalar_one()
        return _task_out(await _task_row(session, task_id), _today(user))


@router.patch("/planner/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: UUID, body: TaskPatch, user: AuthUser, db: UserDbDep) -> TaskOut:
    sent = body.model_fields_set
    for name in ("title", "planned_for", "minutes", "status"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
    if changes.get("status") == "skipped":
        changes["status"] = "cancelled"
    async with db.session() as session:
        row = await _task_row(session, task_id)
        if "title" in changes and row["source"] == "plan":
            raise AppError(409, "plan_task_title", "A planned task keeps its title; add your own task instead.")
        if "subject_id" in changes:
            if row["source"] == "plan":
                raise AppError(409, "plan_task_subject", "A planned task keeps its subject.")
            await _check_subject(session, changes["subject_id"])
        if changes:
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            extra = ""
            if "status" in changes:
                extra += ", completed_at = " + ("now()" if changes["status"] == "done" else "NULL")
            # Moving or resizing a planner task is the student's decision: keep it when the plan
            # is generated again.
            if row["source"] == "plan" and ("planned_for" in changes or "minutes" in changes):
                extra += ", pinned = true"
            await session.execute(
                text(f"UPDATE study_tasks SET {sets}{extra} WHERE id = :id"), {**changes, "id": task_id}
            )
        return _task_out(await _task_row(session, task_id), _today(user))


@router.delete("/planner/tasks/{task_id}", status_code=204)
async def delete_task(task_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(text("DELETE FROM study_tasks WHERE id = :id"), {"id": task_id})
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Task not found.")
    return Response(status_code=204)


# ------------------------------------------------------------------------------ the plan


@router.post("/planner/generate", response_model=GenerateOut)
async def generate_plan(
    body: GenerateIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> GenerateOut:
    await limiter.check(f"plan-generate:{user.id}", 30, 3600)
    today = _today(user)
    last = today + timedelta(days=body.days - 1)
    zone = local_zone(user.timezone).key
    async with db.session() as session:
        prefs = (
            (await session.execute(text("SELECT daily_minutes, days_off FROM study_preferences")))
            .mappings()
            .first()
        )
        daily = prefs["daily_minutes"] if prefs else DEFAULT_DAILY
        days_off = list(prefs["days_off"]) if prefs else []

        exams = [
            ExamItem(str(r["id"]), str(r["subject_id"]) if r["subject_id"] else None,
                     r["name"], r["exam_on"])
            for r in (
                await session.execute(
                    text(
                        "SELECT e.id, e.subject_id, COALESCE(s.name, e.title) AS name, e.exam_on "
                        "FROM exams e LEFT JOIN subjects s ON s.id = e.subject_id "
                        "WHERE e.exam_on > :a AND e.exam_on <= :b"
                    ),
                    {"a": today, "b": last + timedelta(days=1)},
                )
            )
            .mappings()
            .all()
        ]
        assignments = [
            AssignmentItem(str(r["id"]), str(r["subject_id"]) if r["subject_id"] else None,
                           r["title"], r["due"], r["status"] == "in_progress")
            for r in (
                await session.execute(
                    text(
                        "SELECT id, subject_id, title, status, (due_at AT TIME ZONE :tz)::date AS due "
                        "FROM assignments WHERE status <> 'done' AND due_at IS NOT NULL"
                    ),
                    {"tz": zone},
                )
            )
            .mappings()
            .all()
        ]
        weak = [
            WeakSpot(str(r["subject_id"]), r["subject_name"], r["filename"], float(r["acc"]), int(r["n"]))
            for r in (
                await session.execute(
                    text(
                        "SELECT z.subject_id, s.name AS subject_name, q.source->>'filename' AS filename, "
                        "avg(a.score) AS acc, count(*) AS n "
                        "FROM quiz_answers a "
                        "JOIN quiz_questions q ON q.id = a.question_id "
                        "JOIN quiz_attempts t ON t.id = a.attempt_id "
                        "JOIN quizzes z ON z.id = q.quiz_id "
                        "JOIN subjects s ON s.id = z.subject_id "
                        "WHERE a.score IS NOT NULL AND t.status = 'completed' "
                        "AND q.source->>'filename' IS NOT NULL "
                        "GROUP BY z.subject_id, s.name, q.source->>'filename'"
                    )
                )
            )
            .mappings()
            .all()
        ]
        cards = {
            r["d"]: int(r["n"])
            for r in (
                await session.execute(
                    text(
                        "SELECT GREATEST((c.due_at AT TIME ZONE :tz)::date, :today) AS d, count(*) AS n "
                        f"FROM revision_cards c WHERE (c.due_at AT TIME ZONE :tz)::date <= :last AND {CARD_LIVE_SQL} GROUP BY 1"
                    ),
                    {"tz": zone, "today": today, "last": last},
                )
            )
            .mappings()
            .all()
        }
        busy = {
            r["planned_for"]: int(r["m"])
            for r in (
                await session.execute(
                    text(
                        "SELECT planned_for, sum(minutes) AS m FROM study_tasks "
                        "WHERE planned_for >= :today AND status NOT IN ('skipped', 'cancelled') "
                        "AND NOT (source = 'plan' AND status = 'todo' AND NOT pinned) GROUP BY planned_for"
                    ),
                    {"today": today},
                )
            )
            .mappings()
            .all()
        }

        planned = build_plan(
            today=today, horizon=body.days, daily_minutes=daily, days_off=days_off, exams=exams,
            assignments=assignments, weak=weak, cards_by_day=cards, busy=busy,
        )
        # What the student already dealt with is never planned again: planner tasks they finished,
        # cancelled, moved or resized each cancel out one new task about the same thing.
        decided = [
            task_key(
                r["template"],
                str(r["subject_id"]) if r["subject_id"] else None,
                str(r["assignment_id"]) if r["assignment_id"] else None,
                str(r["exam_id"]) if r["exam_id"] else None,
                r["planned_for"],
            )
            for r in (
                await session.execute(
                    text(
                        "SELECT template, subject_id, assignment_id, exam_id, planned_for FROM study_tasks "
                        "WHERE source = 'plan' AND template IS NOT NULL AND (status <> 'todo' OR pinned)"
                    )
                )
            )
            .mappings()
            .all()
        ]
        planned, handled = drop_decided(planned, decided)
        # Only unfinished, unmoved planner tasks from today on are replaced.
        await session.execute(
            text(
                "DELETE FROM study_tasks WHERE source = 'plan' AND status = 'todo' AND NOT pinned "
                "AND planned_for >= :today"
            ),
            {"today": today},
        )
        kept = int(
            (
                await session.execute(
                    text("SELECT count(*) FROM study_tasks WHERE planned_for BETWEEN :a AND :b"),
                    {"a": today, "b": last},
                )
            ).scalar_one()
        )
        for task in planned:
            await session.execute(
                text(
                    "INSERT INTO study_tasks (user_id, subject_id, assignment_id, exam_id, kind, source, "
                    "title, template, params, planned_for, minutes) VALUES (:u, :s, :a, :e, :k, 'plan', "
                    ":t, :tpl, CAST(:p AS jsonb), :d, :m)"
                ),
                {
                    "u": user.id, "s": task.subject_id, "a": task.assignment_id, "e": task.exam_id,
                    "k": task.kind, "t": task.title, "tpl": task.template,
                    "p": json.dumps(task.params, ensure_ascii=False), "d": task.day, "m": task.minutes,
                },
            )
    notice = None if planned else ("up_to_date" if handled else "nothing_to_plan")
    return GenerateOut(
        created=len(planned), first_day=today, last_day=last, notice=notice,
        kept=kept, already_handled=handled,
    )


# ------------------------------------------------------------------------------ calendar


@router.get("/calendar", response_model=CalendarOut)
async def calendar(
    user: AuthUser,
    db: UserDbDep,
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
) -> CalendarOut:
    _check_range(first, last, MAX_CALENDAR_DAYS)
    today = _today(user)
    zone = local_zone(user.timezone).key
    events: list[CalendarEvent] = []
    async with db.session() as session:
        sync = await sync_states(session, user)
        for r in (
            await session.execute(
                text(
                    "SELECT a.id, a.title, a.status, a.due_at, a.subject_id, "
                    "(a.due_at AT TIME ZONE :tz)::date AS day, s.name AS sn "
                    "FROM assignments a LEFT JOIN subjects s ON s.id = a.subject_id "
                    "WHERE a.due_at IS NOT NULL AND (a.due_at AT TIME ZONE :tz)::date BETWEEN :a AND :b"
                ),
                {"tz": zone, "a": first, "b": last},
            )
        ).mappings():
            events.append(CalendarEvent(kind="assignment", day=r["day"], id=r["id"], title=r["title"],
                                        status=r["status"], subject_name=r["sn"],
                                        subject_id=r["subject_id"], due_at=r["due_at"],
                                        sync=sync.get(("assignment", str(r["id"])))))
        for r in (
            await session.execute(
                text(
                    "SELECT e.id, e.title, e.exam_on AS day, e.subject_id, s.name AS sn FROM exams e "
                    "LEFT JOIN subjects s ON s.id = e.subject_id WHERE e.exam_on BETWEEN :a AND :b"
                ),
                {"a": first, "b": last},
            )
        ).mappings():
            events.append(CalendarEvent(kind="exam", day=r["day"], id=r["id"], title=r["title"],
                                        subject_name=r["sn"], subject_id=r["subject_id"],
                                        sync=sync.get(("exam", str(r["id"])))))
        for r in (
            await session.execute(
                text(f"{_TASK_SQL} WHERE t.planned_for BETWEEN :a AND :b ORDER BY t.planned_for, t.created_at"),
                {"a": first, "b": last},
            )
        ).mappings():
            events.append(CalendarEvent(
                kind="task", day=r["planned_for"], id=r["id"], title=r["title"], status=r["status"],
                minutes=r["minutes"], template=r["template"], params=as_json(r["params"]) or {},
                subject_name=r["subject_name"], subject_id=r["subject_id"],
                assignment_id=r["assignment_id"], exam_id=r["exam_id"], source=r["source"],
                state=task_state(r["status"], r["planned_for"], today),
                sync=sync.get(("task", str(r["id"]))),
            ))
        for r in (
            await session.execute(
                text(
                    "SELECT e.id, e.title, e.notes, e.day, e.start_time, e.minutes, e.subject_id, "
                    "e.sync_to_google, s.name AS sn FROM calendar_events e "
                    "LEFT JOIN subjects s ON s.id = e.subject_id WHERE e.day BETWEEN :a AND :b"
                ),
                {"a": first, "b": last},
            )
        ).mappings():
            events.append(CalendarEvent(
                kind="event", day=r["day"], id=r["id"], title=r["title"], notes=r["notes"],
                start_time=r["start_time"], minutes=r["minutes"], subject_id=r["subject_id"],
                subject_name=r["sn"], sync_to_google=r["sync_to_google"],
                sync=sync.get(("event", str(r["id"]))) if r["sync_to_google"] else None,
            ))
        # Cards due: shown as one entry per day with a count; overdue ones sit on today.
        for r in (
            await session.execute(
                text(
                    "SELECT GREATEST((c.due_at AT TIME ZONE :tz)::date, :today) AS day, count(*) AS n "
                    f"FROM revision_cards c WHERE {CARD_LIVE_SQL} AND "
                    "GREATEST((c.due_at AT TIME ZONE :tz)::date, :today) "
                    "BETWEEN :a AND :b GROUP BY 1"
                ),
                {"tz": zone, "today": today, "a": first, "b": last},
            )
        ).mappings():
            events.append(CalendarEvent(kind="revision", day=r["day"], count=int(r["n"])))
    order = ["exam", "assignment", "event", "task", "revision"]
    events.sort(key=lambda e: (e.day, order.index(e.kind), e.start_time or "", e.title))
    return CalendarOut(today=today, events=events)
