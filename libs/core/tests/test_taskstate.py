from datetime import date

from mindnest_core.taskstate import TASK_STATES, counts, task_state

TODAY = date(2026, 10, 30)


def test_done_is_completed_even_when_late():
    assert task_state("done", date(2026, 10, 1), TODAY) == "completed"


def test_skipped_and_cancelled_are_cancelled_and_never_overdue():
    assert task_state("skipped", date(2026, 10, 1), TODAY) == "cancelled"
    assert task_state("cancelled", date(2026, 10, 1), TODAY) == "cancelled"


def test_a_todo_before_today_is_overdue_today_or_later_is_pending():
    assert task_state("todo", date(2026, 10, 29), TODAY) == "overdue"
    assert task_state("todo", TODAY, TODAY) == "pending"
    assert task_state("todo", date(2026, 11, 2), TODAY) == "pending"
    assert task_state("todo", None, TODAY) == "pending"


def test_counts_always_has_all_four_states():
    assert counts([]) == dict.fromkeys(TASK_STATES, 0)
    assert counts(["pending", "pending", "overdue"])["pending"] == 2
