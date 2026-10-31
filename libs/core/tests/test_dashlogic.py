"""The dashboard rules: one definition of every figure (see mindnest_core.dashlogic)."""

from datetime import date, timedelta

from mindnest_core import dashlogic as dl

TODAY = date(2026, 10, 27)


def task(status="todo", day=TODAY, title="Read chapter 1", source="plan", minutes=30, **extra):  # type: ignore[no-untyped-def]
    return dl.TaskRow(
        id=extra.pop("id", title), title=title, planned_for=day, minutes=minutes, status=status,
        kind=extra.pop("kind", "revise"), source=source, **extra,
    )


def test_a_student_with_nothing_graded_has_no_average():
    assert dl.average(None, None) is None
    assert dl.average(0, 0) is None
    assert dl.average(3, 4) == 0.75


def test_the_average_is_pooled_so_a_long_quiz_weighs_more():
    # 1/1 and 1/9 pooled is 2/10, not the mean of 100% and 11%.
    assert dl.average(2, 10) == 0.2


def test_a_topic_needs_enough_answers_to_be_weak():
    assert not dl.is_weak(0.1, dl.WEAK_MIN_ANSWERS - 1)
    assert dl.is_weak(0.5, dl.WEAK_MIN_ANSWERS)
    assert not dl.is_weak(dl.WEAK_BELOW, 10)
    assert not dl.is_weak(None, 10)


def test_the_streak_survives_a_day_that_is_not_over_yet():
    yesterday = TODAY - timedelta(days=1)
    assert dl.streak(set(), TODAY) == 0
    assert dl.streak({yesterday, yesterday - timedelta(days=1)}, TODAY) == 2
    assert dl.streak({TODAY, yesterday}, TODAY) == 2
    # A gap two days ago ends it.
    assert dl.streak({TODAY, TODAY - timedelta(days=2)}, TODAY) == 1


def test_days_left_is_negative_once_a_deadline_has_passed():
    assert dl.days_left(TODAY + timedelta(days=3), TODAY) == 3
    assert dl.days_left(TODAY - timedelta(days=2), TODAY) == -2


def test_task_states_are_shared_not_rederived():
    yesterday = TODAY - timedelta(days=1)
    assert dl.state_of(task("done", yesterday), TODAY) == "completed"
    assert dl.state_of(task("todo", yesterday), TODAY) == "overdue"
    assert dl.state_of(task("todo", TODAY), TODAY) == "pending"
    assert dl.state_of(task("skipped", yesterday), TODAY) == "cancelled"


def test_two_identical_tasks_count_once_and_the_finished_copy_wins():
    rows = [task("todo", title="Revise  Cells"), task("done", title="revise cells"), task(title="Other")]
    kept = dl.dedupe_tasks(rows)
    assert len(kept) == 2
    assert [r.status for r in kept if _squash(r.title) == "revise cells"] == ["done"]


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def test_a_manual_task_and_a_planned_one_with_the_same_title_are_different_tasks():
    assert len(dl.dedupe_tasks([task(source="plan"), task(source="manual")])) == 2


def test_tasks_are_ordered_overdue_then_pending_then_completed_then_cancelled():
    yesterday = TODAY - timedelta(days=1)
    rows = [
        task("skipped", title="d"), task("done", title="c"), task("todo", title="b"),
        task("todo", yesterday, title="a"),
    ]
    assert [r.title for r in dl.order_tasks(rows, TODAY)] == ["a", "b", "c", "d"]


def test_the_summary_leaves_cancelled_tasks_out_of_the_totals():
    rows = [task("done", minutes=20, title="a"), task("todo", minutes=40, title="b"), task("skipped", minutes=60, title="c")]
    summary = dl.summarise_tasks(rows, TODAY)
    assert (summary.total, summary.done) == (2, 1)
    assert (summary.minutes_total, summary.minutes_done) == (60, 20)
    assert summary.states == {"pending": 1, "completed": 1, "overdue": 0, "cancelled": 1}


def test_windows_are_consistent_with_each_other():
    first, last = dl.overdue_task_window(TODAY)
    assert last == TODAY - timedelta(days=1) and (TODAY - first).days == dl.OVERDUE_TASK_LOOKBACK_DAYS
    a_first, a_last = dl.assignment_window(TODAY)
    d_first, d_last = dl.deadline_window(TODAY)
    assert a_first == d_first and a_last <= d_last


def test_every_dashboard_item_leads_somewhere():
    assert dl.assignment_href("abc") == "/assignments/abc"
    assert dl.deadline_href("assignment", "abc", TODAY) == "/assignments/abc"
    assert dl.deadline_href("exam", "e1", TODAY).startswith("/calendar?day=2026-10-27")
    assert dl.weak_topic_href("s1", "m1") == "/subjects/s1?doc=m1"
    assert dl.weak_topic_href("s1", None) == "/subjects/s1?tab=progress"
    assert dl.activity_href("chat", "c1") == "/chat?c=c1"
    assert dl.activity_href("quiz", "a1") == "/quizzes/attempt/a1"
    assert dl.activity_href("material", "m1") == "/subjects"
    assert dl.activity_href("material", "m1", subject_id="s1") == "/subjects/s1?doc=m1"
    assert dl.activity_href("task", "t1") == "/planner"
    assert dl.activity_href("nonsense", "x") == "/dashboard"
    assert dl.task_href(task(kind="quiz")) == "/quizzes"
    assert dl.task_href(task(kind="assignment", assignment_id="a9")) == "/assignments/a9"
    assert dl.task_href(task(kind="custom")) == f"/planner?day={TODAY.isoformat()}"
