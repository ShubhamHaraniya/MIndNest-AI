"""How every number on the dashboard is worked out. Pure functions: no database, no clock.

The dashboard, the Quizzes page, the Subjects page, the planner and the calendar all show figures
about the same data. They only agree if they all follow the same rules, so the rules live here and
the dashboard route (and, for the weak-topic rule, the Subjects route) imports them.

Rules, in one place
-------------------
Scope
    The dashboard shows either "all courses" or one course. A course scopes the *content* of the
    page: documents, quizzes and their average, chats, revision cards, weak topics, deadlines,
    assignments, recent activity. The student's *day* (today's schedule, the week ahead, study
    minutes, the streak) is the same for every course because the planner and the calendar are not
    filtered by course either. An unknown or archived course id means "all courses".

Counts
    * subjects         - courses that are not archived.
    * materials        - not deleted, in a course that is not archived (what the Subjects page
                         lists); "ready" is the subset whose reading has finished.
    * quiz attempts    - completed attempts that have at least one graded point (``total > 0``).
                         An attempt that is submitted but still being graded is not counted.
    * quiz average     - points over total across those attempts (a pooled mean, so a long quiz
                         weighs more than a short one), 0..1; ``None`` when there is no attempt.
    * conversations    - every conversation (scoped: the ones started in that course).
    * revision due     - spaced-revision cards whose due day (student's time zone) is today or
                         earlier, in a course that is not archived (``quizstore.CARD_DUE_SQL``);
                         scoped: that course. Every screen uses the same SQL.

Weak topic
    A source document counts as weak when the student has answered at least ``WEAK_MIN_ANSWERS``
    marked questions from it in completed attempts and averages under ``WEAK_BELOW``.

Tasks (state comes from ``taskstate.task_state``; "today" is the student's own date)
    * pending / completed / overdue / cancelled - never re-derived anywhere else.
    * today's total        - today's tasks that are not cancelled; done = completed ones.
    * study minutes        - minutes of completed tasks, on the day the task was planned for.
    * overdue              - still-to-do tasks planned for an earlier day, looked at for the last
                             ``OVERDUE_TASK_LOOKBACK_DAYS`` days.
    * duplicates           - tasks with the same source, day and title are one task (``task_key``).

Streak
    Days in a row on which the student completed a task or finished a quiz (in their own time
    zone). A day that is not over yet does not break the streak.

Deadlines
    Exams from today on and assignments not yet done, both within ``DEADLINE_WINDOW_DAYS``;
    assignments that slipped past are kept for ``OVERDUE_LOOKBACK_DAYS`` (the same window as the
    notification bell). ``days_left`` is negative once a deadline is past.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from mindnest_core.taskstate import TaskState, counts, task_state

WEEK_DAYS = 7
STREAK_LOOKBACK_DAYS = 90
DEADLINE_WINDOW_DAYS = 60
ASSIGNMENT_WINDOW_DAYS = 14
OVERDUE_LOOKBACK_DAYS = 14
OVERDUE_TASK_LOOKBACK_DAYS = 14
WEAK_BELOW = 0.8  # a document counts as weak under this average score
WEAK_MIN_ANSWERS = 3

# Overdue first (it needs the student), then what is left, then what is finished or dropped.
_STATE_ORDER: dict[str, int] = {"overdue": 0, "pending": 1, "completed": 2, "cancelled": 3}
# When two copies of a task exist, keep the one furthest along so a finished tick is never lost.
_STATUS_RANK: dict[str, int] = {"done": 0, "todo": 1, "skipped": 2, "cancelled": 2}


# ------------------------------------------------------------------------------ numbers


def streak(active: set[date], today: date) -> int:
    """Days in a row with some study activity. A day not finished yet does not break the streak."""
    day = today if today in active else today - timedelta(days=1)
    count = 0
    while day in active:
        count += 1
        day -= timedelta(days=1)
    return count


def average(points: float | None, total: float | None) -> float | None:
    """Pooled score over graded attempts, 0..1 rounded to four places; None with nothing graded."""
    if points is None or total is None or total <= 0:
        return None
    return round(float(points) / float(total), 4)


def is_weak(accuracy: float | None, answers: int) -> bool:
    """The one rule for a weak topic or document (see the module notes)."""
    return accuracy is not None and answers >= WEAK_MIN_ANSWERS and accuracy < WEAK_BELOW


def days_left(on: date, today: date) -> int:
    """Whole days until `on`; negative once it has passed."""
    return (on - today).days


def deadline_window(today: date) -> tuple[date, date]:
    """First and last day an upcoming deadline can fall on to be listed."""
    return today - timedelta(days=OVERDUE_LOOKBACK_DAYS), today + timedelta(days=DEADLINE_WINDOW_DAYS)


def assignment_window(today: date) -> tuple[date, date]:
    """First and last due day of the assignments panel (a little overdue, two weeks ahead)."""
    return today - timedelta(days=OVERDUE_LOOKBACK_DAYS), today + timedelta(days=ASSIGNMENT_WINDOW_DAYS)


def overdue_task_window(today: date) -> tuple[date, date]:
    """Days whose unfinished tasks are listed as overdue: the last two weeks up to yesterday."""
    return today - timedelta(days=OVERDUE_TASK_LOOKBACK_DAYS), today - timedelta(days=1)


# --------------------------------------------------------------------------------- tasks


@dataclass(frozen=True)
class TaskRow:
    """The parts of a study task the dashboard needs, whatever the query it came from."""

    id: Any
    title: str
    planned_for: date
    minutes: int
    status: str  # todo | done | skipped | cancelled
    kind: str  # revise | assignment | quiz | custom
    source: str  # plan | manual
    template: str | None = None
    params: Any = None
    subject_id: Any = None
    subject_name: str | None = None
    assignment_id: Any = None
    exam_id: Any = None


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def task_key(row: TaskRow) -> tuple[str, date, str]:
    """What makes two tasks "the same": same origin, same day, same title (ignoring case/space)."""
    return (row.source, row.planned_for, _squash(row.title))


def dedupe_tasks(rows: Iterable[TaskRow]) -> list[TaskRow]:
    """Each distinct task once, in the order its first copy appeared. The copy furthest along wins
    (done over to-do over dropped), so ticking one of two identical tasks is not undone by the
    other."""
    chosen: dict[tuple[str, date, str], TaskRow] = {}
    for row in rows:
        key = task_key(row)
        held = chosen.get(key)
        if held is None or _STATUS_RANK.get(row.status, 1) < _STATUS_RANK.get(held.status, 1):
            chosen[key] = row
    return list(chosen.values())


def state_of(row: TaskRow, today: date) -> TaskState:
    return task_state(row.status, row.planned_for, today)


def order_tasks(rows: Sequence[TaskRow], today: date) -> list[TaskRow]:
    """Overdue, then pending, then completed, then cancelled; stable inside each group."""
    return sorted(rows, key=lambda r: _STATE_ORDER[state_of(r, today)])


def counts_by_state(rows: Sequence[TaskRow], today: date) -> dict[str, int]:
    """How many of these tasks are in each shared state (all four keys always present)."""
    return counts([state_of(r, today) for r in rows])


@dataclass(frozen=True)
class TaskSummary:
    states: dict[str, int]  # all four task states, always present
    total: int  # tasks that are not cancelled
    done: int
    minutes_total: int  # minutes of the tasks that are not cancelled
    minutes_done: int


def summarise_tasks(rows: Sequence[TaskRow], today: date) -> TaskSummary:
    """Figures for a set of tasks, using the shared state and the shared notion of "cancelled"."""
    states = [state_of(r, today) for r in rows]
    live = [r for r, s in zip(rows, states, strict=True) if s != "cancelled"]
    finished = [r for r, s in zip(rows, states, strict=True) if s == "completed"]
    return TaskSummary(
        states=counts(states),
        total=len(live),
        done=len(finished),
        minutes_total=sum(r.minutes for r in live),
        minutes_done=sum(r.minutes for r in finished),
    )


# ------------------------------------------------------------------------------- links


def planner_href(day: date) -> str:
    return f"/planner?day={day.isoformat()}"


def calendar_href(day: date) -> str:
    return f"/calendar?day={day.isoformat()}"


def assignment_href(assignment_id: Any) -> str:
    return f"/assignments/{assignment_id}"


def attempt_href(attempt_id: Any) -> str:
    return f"/quizzes/attempt/{attempt_id}"


def chat_href(conversation_id: Any) -> str:
    return f"/chat?c={conversation_id}"


def course_href(subject_id: Any, *, doc: Any = None, tab: str | None = None) -> str:
    base = f"/subjects/{subject_id}"
    if doc is not None:
        return f"{base}?doc={doc}"
    return f"{base}?tab={tab}" if tab else base


def task_href(row: TaskRow) -> str:
    """Where a task leads: its assignment's workspace, the quizzes for revision and quiz tasks
    (as the planner does), otherwise its day in the planner."""
    if row.kind == "assignment" and row.assignment_id is not None:
        return assignment_href(row.assignment_id)
    if row.kind in ("revise", "quiz"):
        return "/quizzes"
    return planner_href(row.planned_for)


def deadline_href(kind: str, ident: Any, on: date) -> str:
    """An assignment opens its workspace; an exam opens its day in the calendar."""
    return assignment_href(ident) if kind == "assignment" else calendar_href(on)


def weak_topic_href(subject_id: Any, material_id: Any) -> str:
    """The document itself when it can be found, else the course's topic-progress tab."""
    if material_id is not None:
        return course_href(subject_id, doc=material_id)
    return course_href(subject_id, tab="progress")


def activity_href(kind: str, ref: Any, *, subject_id: Any = None, day: date | None = None) -> str:
    """Where a row of "recent activity" leads. `ref` is the id of the thing the row is about:
    the conversation, the quiz attempt, the document, the task or the assignment."""
    if kind == "chat":
        return chat_href(ref)
    if kind == "quiz":
        return attempt_href(ref)
    if kind == "material":
        return course_href(subject_id, doc=ref) if subject_id is not None else "/subjects"
    if kind == "task":
        return planner_href(day) if day is not None else "/planner"
    if kind == "assignment":
        return assignment_href(ref)
    return "/dashboard"


# ------------------------------------------------------------------------- getting started


@dataclass(frozen=True)
class SetupFacts:
    """What is true of the student's account right now (counts, never guesses)."""

    courses: int
    materials: int
    quiz_attempts: int
    conversations: int
    has_institution: bool
    provider_keys: int
    first_course_id: Any = None


@dataclass(frozen=True)
class SetupStep:
    key: str  # course | material | institution | provider | chat | quiz
    done: bool
    href: str


CORE_STEPS = ("course", "material", "institution", "provider")


def setup_steps(facts: SetupFacts) -> list[SetupStep]:
    """The guided "get started" checklist, each step done or not by the student's real data."""
    upload_href = (
        course_href(facts.first_course_id, tab="documents")
        if facts.first_course_id is not None
        else "/subjects?new=1"
    )
    return [
        SetupStep("course", facts.courses > 0, "/subjects?new=1"),
        SetupStep("material", facts.materials > 0, upload_href),
        SetupStep("institution", facts.has_institution, "/settings?tab=account"),
        SetupStep("provider", facts.provider_keys > 0, "/settings?tab=providers"),
        SetupStep("chat", facts.conversations > 0, "/chat"),
        SetupStep("quiz", facts.quiz_attempts > 0, "/quizzes"),
    ]


def needs_setup(steps: Sequence[SetupStep]) -> bool:
    """Show the checklist while any of the four basics is still open."""
    return any(not s.done for s in steps if s.key in CORE_STEPS)
