"""One definition of what state a study task is in, used by the dashboard, planner and calendar.

Stored task status is todo | done | skipped | cancelled. What the student is shown is derived from
that and the task's own due day, in the student's own timezone ("today" is passed in, never read
from a clock here), so every page agrees:

* completed - done
* cancelled - skipped or cancelled (dropped on purpose; never counts as overdue)
* overdue   - still to do and its day is before today
* pending   - still to do, due today or later (or with no day)
"""

from datetime import date
from typing import Literal

TaskState = Literal["pending", "completed", "overdue", "cancelled"]
TASK_STATES: tuple[TaskState, ...] = ("pending", "completed", "overdue", "cancelled")


def task_state(status: str, due: date | None, today: date) -> TaskState:
    if status == "done":
        return "completed"
    if status in ("skipped", "cancelled"):
        return "cancelled"
    if due is not None and due < today:
        return "overdue"
    return "pending"


def counts(states: list[TaskState]) -> dict[str, int]:
    """How many tasks are in each state (all four keys always present)."""
    result: dict[str, int] = dict.fromkeys(TASK_STATES, 0)
    for state in states:
        result[state] += 1
    return result
