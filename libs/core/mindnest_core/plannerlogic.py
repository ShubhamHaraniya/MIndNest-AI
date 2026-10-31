"""The study planner's scheduling rules. Pure functions: no database, no clock, no network.

The planner is deliberately not an AI. It spreads work over the days before each exam and
assignment deadline, puts spaced-revision cards on the days they fall due, and gives extra time
to the material the student's quiz answers show is weakest. The same inputs always give the same
plan, so the student can see why each task is where it is.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_DAILY, MAX_DAILY, DEFAULT_DAILY = 20, 480, 90
MIN_HORIZON, MAX_HORIZON, DEFAULT_HORIZON = 7, 28, 14
MAX_EXAM_SESSIONS = 8
WEAK_BELOW = 0.70  # a file the student scores under this in quizzes counts as weak
WEAK_QUIZ_BELOW = 0.65
MIN_WEAK_ANSWERS = 3
MIN_FREE_TO_SUGGEST = 20  # a day needs this many free minutes to be offered as a place to move work

# English wording, used as the stored title and as a fallback. The web app translates the same
# templates (planner.t.<template>) into the student's own language.
TITLES = {
    "assignment_plan": "Plan: {title}",
    "assignment_write": "Work on: {title}",
    "assignment_review": "Review and polish: {title}",
    "exam_revise": "Revise {subject}",
    "exam_weak": "Revise {name} ({percent}% in your quizzes)",
    "exam_final": "Final revision: {subject}",
    "cards_due": "Spaced revision: {count} cards",
    "weak_quiz": "Practise {subject} with a quiz ({percent}% so far)",
}


def render_title(template: str, params: Mapping[str, Any]) -> str:
    return TITLES[template].format(**params)


def local_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(timezone: str, now: datetime) -> date:
    """The calendar date it is for the student right now."""
    return now.astimezone(local_zone(timezone)).date()


@dataclass(frozen=True)
class ExamItem:
    id: str
    subject_id: str | None
    subject_name: str
    day: date


@dataclass(frozen=True)
class AssignmentItem:
    id: str
    subject_id: str | None
    title: str
    due: date | None
    in_progress: bool = False


@dataclass(frozen=True)
class WeakSpot:
    subject_id: str
    subject_name: str
    filename: str
    accuracy: float  # 0..1
    answers: int


@dataclass
class PlanTask:
    kind: str  # revise | assignment | quiz
    template: str
    params: dict[str, Any]
    day: date
    minutes: int
    subject_id: str | None = None
    assignment_id: str | None = None
    exam_id: str | None = None

    @property
    def title(self) -> str:
        return render_title(self.template, self.params)


@dataclass
class _Calendar:
    """Study days and the minutes still free on each."""

    days: list[date]
    free: dict[date, int] = field(default_factory=dict)

    def nearest(self, target: date, first: date, last: date) -> date | None:
        window = [d for d in self.days if first <= d <= last]
        if not window:
            return None
        return min(window, key=lambda d: (abs((d - target).days), d))

    def place(self, target: date, minutes: int, first: date, last: date) -> date | None:
        """The study day closest to `target` (inside first..last) that still has room; if none
        has, the day with the most room. Returns None when the window has no study day."""
        window = sorted(
            (d for d in self.days if first <= d <= last), key=lambda d: (abs((d - target).days), d)
        )
        if not window:
            return None
        chosen = next((d for d in window if self.free[d] >= minutes), None)
        if chosen is None:
            chosen = max(window, key=lambda d: (self.free[d], -abs((d - target).days)))
        self.free[chosen] = max(0, self.free[chosen] - minutes)
        return chosen


def card_minutes(count: int) -> int:
    """About 45 seconds a card, never less than 10 or more than 30 minutes."""
    return max(10, min(30, math.ceil(count * 0.75)))


def subject_accuracy(weak: Sequence[WeakSpot]) -> dict[str, tuple[str, float, int]]:
    """subject id -> (name, answer-weighted accuracy, answers)."""
    totals: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for spot in weak:
        row = totals.setdefault(spot.subject_id, [0.0, 0.0])
        row[0] += spot.accuracy * spot.answers
        row[1] += spot.answers
        names[spot.subject_id] = spot.subject_name
    return {sid: (names[sid], row[0] / row[1], int(row[1])) for sid, row in totals.items() if row[1]}


def build_plan(
    *,
    today: date,
    horizon: int,
    daily_minutes: int,
    days_off: Sequence[int],
    exams: Sequence[ExamItem],
    assignments: Sequence[AssignmentItem],
    weak: Sequence[WeakSpot],
    cards_by_day: Mapping[date, int],
    busy: Mapping[date, int] | None = None,
) -> list[PlanTask]:
    """The tasks to schedule from `today` for `horizon` days.

    `days_off` are weekday numbers (Monday = 0) with no studying. `cards_by_day` is how many
    revision cards fall due each day (cards already overdue count on `today`). `busy` is minutes
    already taken on a day by tasks the student added or finished themselves.
    """
    horizon = max(MIN_HORIZON, min(MAX_HORIZON, horizon))
    last_day = today + timedelta(days=horizon - 1)
    study_days = [
        today + timedelta(days=i)
        for i in range(horizon)
        if (today + timedelta(days=i)).weekday() not in set(days_off)
    ]
    cal = _Calendar(study_days, {d: max(0, daily_minutes - (busy or {}).get(d, 0)) for d in study_days})
    tasks: list[PlanTask] = []
    subjects_with_exam: set[str] = set()

    # 1. Revision cards stay on the day they are due (or the next study day).
    for day in sorted(cards_by_day):
        count = cards_by_day[day]
        if count <= 0 or day > last_day:
            continue
        placed = cal.nearest(max(day, today), max(day, today), last_day)
        if placed is None:
            continue
        minutes = card_minutes(count)
        cal.free[placed] = max(0, cal.free[placed] - minutes)
        tasks.append(PlanTask("revise", "cards_due", {"count": count}, placed, minutes))

    # 2. Exams: sessions spread over the days before, the last one on the eve of the exam.
    by_subject: dict[str, list[WeakSpot]] = {}
    for spot in sorted(weak, key=lambda s: s.accuracy):
        if spot.accuracy < WEAK_BELOW and spot.answers >= MIN_WEAK_ANSWERS:
            by_subject.setdefault(spot.subject_id, []).append(spot)
    for exam in sorted(exams, key=lambda e: e.day):
        days_left = (exam.day - today).days
        if days_left < 1 or exam.day > last_day + timedelta(days=1):
            continue
        if exam.subject_id:
            subjects_with_exam.add(exam.subject_id)
        sessions = 1 if days_left == 1 else min(MAX_EXAM_SESSIONS, max(2, days_left // 2))
        eve = exam.day - timedelta(days=1)
        window_last = min(eve, last_day)
        spots = by_subject.get(exam.subject_id or "", [])
        step = (days_left - 1) / sessions
        for i in range(sessions):
            is_final = i == sessions - 1
            target = eve if is_final else today + timedelta(days=int(i * step))
            params: dict[str, Any]
            if is_final:
                template, params, minutes = "exam_final", {"subject": exam.subject_name}, 45
            elif i < len(spots):
                spot = spots[i]
                template = "exam_weak"
                params = {"name": spot.filename, "percent": round(spot.accuracy * 100)}
                minutes = 40
            else:
                template, params, minutes = "exam_revise", {"subject": exam.subject_name}, 40
            placed_on = cal.place(target, minutes, today, window_last)
            if placed_on is not None:
                tasks.append(
                    PlanTask("revise", template, params, placed_on, minutes, exam.subject_id, None, exam.id)
                )

    # 3. Assignments with a deadline, nearest first.
    for item in sorted((a for a in assignments if a.due is not None), key=lambda a: a.due or today):
        due = item.due
        assert due is not None
        days_left = (due - today).days
        if days_left > horizon:
            continue
        window_last = max(today, min(due - timedelta(days=1), last_day)) if days_left >= 1 else today
        if days_left <= 1:
            plan = [("assignment_write", 60, window_last)]
        elif days_left <= 3:
            plan = [("assignment_write", 60, today + timedelta(days=days_left // 2)),
                    ("assignment_review", 30, window_last)]
        else:
            plan = [("assignment_plan", 45, today),
                    ("assignment_write", 60, today + timedelta(days=int((days_left - 1) * 0.55))),
                    ("assignment_review", 30, window_last)]
        if item.in_progress:
            plan = [step for step in plan if step[0] != "assignment_plan"]
        for template, minutes, target in plan:
            placed_on = cal.place(target, minutes, today, window_last)
            if placed_on is not None:
                tasks.append(
                    PlanTask("assignment", template, {"title": item.title}, placed_on, minutes,
                             item.subject_id, item.id)
                )

    # 4. Quizzes on the weakest subjects that have no exam coming up.
    weakest = sorted(
        (
            (sid, name, acc)
            for sid, (name, acc, answers) in subject_accuracy(weak).items()
            if acc < WEAK_QUIZ_BELOW and answers >= MIN_WEAK_ANSWERS and sid not in subjects_with_exam
        ),
        key=lambda row: row[2],
    )[:3]
    for position, (sid, name, acc) in enumerate(weakest):
        placed_on = cal.place(today + timedelta(days=1 + 2 * position), 20, today, last_day)
        if placed_on is not None:
            tasks.append(
                PlanTask("quiz", "weak_quiz", {"subject": name, "percent": round(acc * 100)}, placed_on, 20, sid)
            )

    tasks.sort(key=lambda t: (t.day, t.kind, t.template))
    return tasks


# ------------------------------------------------------------------ keeping what the student decided


def task_key(
    template: str | None,
    subject_id: str | None,
    assignment_id: str | None,
    exam_id: str | None,
    day: date,
) -> tuple[str, str, str, str, str]:
    """What a planner task is *about*, so a regenerated plan can tell it already exists.

    The day is part of the key only for spaced-revision tasks (they belong to the day the cards
    fall due); every other task is "that step for that exam or assignment", wherever it sits.
    """
    template = template or ""
    return (
        template,
        subject_id or "",
        assignment_id or "",
        exam_id or "",
        day.isoformat() if template == "cards_due" else "",
    )


def drop_decided(
    planned: Sequence[PlanTask], decided: Sequence[tuple[str, str, str, str, str]]
) -> tuple[list[PlanTask], int]:
    """Remove the new tasks the student has already finished, cancelled, moved or pinned.

    `decided` holds the keys of planner tasks that must survive regeneration. Each one cancels
    out one new task with the same key, so an exam with three revision sessions where one was
    finished gets two more, not three. Returns the tasks to create and how many were dropped.
    """
    remaining: dict[tuple[str, str, str, str, str], int] = {}
    for key in decided:
        remaining[key] = remaining.get(key, 0) + 1
    kept: list[PlanTask] = []
    dropped = 0
    for task in planned:
        key = task_key(task.template, task.subject_id, task.assignment_id, task.exam_id, task.day)
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
            dropped += 1
        else:
            kept.append(task)
    return kept, dropped


@dataclass(frozen=True)
class Overload:
    """A day with more planned than the student said they can do (or any work on a day off)."""

    day: date
    minutes: int
    limit: int
    day_off: bool
    suggested: date | None  # a nearby study day with room, when there is one

    @property
    def excess(self) -> int:
        return self.minutes if self.day_off else self.minutes - self.limit


def find_overloads(
    load: Mapping[date, int],
    *,
    daily_minutes: int,
    days_off: Sequence[int],
    today: date,
    last: date,
) -> list[Overload]:
    """Days from `today` to `last` that are too full, with a lighter day to move work to.

    `load` is the minutes of work on each day (tasks that were cancelled are not counted).
    """
    off = set(days_off)
    found: list[Overload] = []
    for day in sorted(load):
        minutes = load[day]
        if day < today or day > last or minutes <= 0:
            continue
        day_off = day.weekday() in off
        if not day_off and minutes <= daily_minutes:
            continue
        candidates = [
            day + timedelta(days=step)
            for step in range(-7, 8)
            if step != 0
        ]
        roomy = [
            c
            for c in candidates
            if today <= c <= last
            and c.weekday() not in off
            and daily_minutes - load.get(c, 0) >= MIN_FREE_TO_SUGGEST
        ]
        suggested = (
            min(roomy, key=lambda c: (abs((c - day).days), -(daily_minutes - load.get(c, 0)), c))
            if roomy
            else None
        )
        found.append(Overload(day, minutes, daily_minutes, day_off, suggested))
    return found
