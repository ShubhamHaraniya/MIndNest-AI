"""Study-planner scheduling rules."""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from mindnest_core.plannerlogic import (
    TITLES,
    AssignmentItem,
    ExamItem,
    WeakSpot,
    build_plan,
    card_minutes,
    drop_decided,
    find_overloads,
    local_today,
    render_title,
    subject_accuracy,
    task_key,
)

TODAY = date(2026, 11, 2)  # a Monday


def plan(**overrides):  # type: ignore[no-untyped-def]
    args = {
        "today": TODAY, "horizon": 14, "daily_minutes": 90, "days_off": [], "exams": [],
        "assignments": [], "weak": [], "cards_by_day": {}, "busy": None,
    }
    args.update(overrides)
    return build_plan(**args)


def days(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def exam(offset: int, subject: str = "s1", name: str = "Biology") -> ExamItem:
    return ExamItem(f"e{offset}", subject, name, days(offset))


# ------------------------------------------------------------------ cards


def test_cards_stay_on_the_day_they_fall_due_and_overdue_ones_count_today():
    tasks = plan(cards_by_day={days(0): 12, days(3): 4})
    cards = {t.day: t for t in tasks if t.template == "cards_due"}
    assert set(cards) == {days(0), days(3)}
    assert cards[days(0)].params == {"count": 12} and cards[days(0)].minutes == 10


def test_card_time_is_between_ten_and_thirty_minutes():
    assert card_minutes(1) == 10 and card_minutes(20) == 15 and card_minutes(500) == 30


def test_a_day_off_pushes_cards_to_the_next_study_day():
    tasks = plan(days_off=[days(3).weekday()], cards_by_day={days(3): 5})
    (card,) = tasks
    assert card.day == days(4)


def test_cards_beyond_the_horizon_are_left_out():
    assert plan(cards_by_day={days(20): 5}) == []


# ------------------------------------------------------------------ exams


def test_exam_sessions_are_spread_end_on_the_eve_and_never_on_or_after_the_exam():
    tasks = plan(exams=[exam(10)])
    assert tasks and all(t.kind == "revise" for t in tasks)
    assert all(today_ok(t.day) and t.day < days(10) for t in tasks)
    final = [t for t in tasks if t.template == "exam_final"]
    assert len(final) == 1 and final[0].day == days(9)
    assert len({t.day for t in tasks}) >= 4  # spread, not piled up
    assert len(tasks) == 5  # 10 days left -> 5 sessions


def today_ok(day: date) -> bool:
    return day >= TODAY


def test_an_exam_tomorrow_gets_one_session_today():
    (task,) = plan(exams=[exam(1)])
    assert task.day == TODAY and task.template == "exam_final"


def test_an_exam_today_or_in_the_past_gets_nothing():
    assert plan(exams=[exam(0), exam(-3)]) == []


def test_an_exam_far_beyond_the_horizon_is_not_planned_yet():
    assert plan(exams=[exam(40)]) == []


def test_weak_files_are_revised_first_weakest_first():
    weak = [
        WeakSpot("s1", "Biology", "chapter2.pdf", 0.40, 10),
        WeakSpot("s1", "Biology", "chapter1.pdf", 0.55, 8),
        WeakSpot("s1", "Biology", "chapter3.pdf", 0.95, 9),  # strong: not chosen
        WeakSpot("s2", "Physics", "optics.pdf", 0.10, 9),  # another subject
    ]
    tasks = plan(exams=[exam(12)], weak=weak)
    named = [t.params["name"] for t in tasks if t.template == "exam_weak"]
    assert named == ["chapter2.pdf", "chapter1.pdf"]
    first = next(t for t in sorted(tasks, key=lambda t: t.day) if t.template == "exam_weak")
    assert first.params == {"name": "chapter2.pdf", "percent": 40}


def test_a_few_answers_are_not_enough_to_call_a_file_weak():
    weak = [WeakSpot("s1", "Biology", "chapter2.pdf", 0.0, 2)]
    tasks = plan(exams=[exam(12)], weak=weak)
    assert not [t for t in tasks if t.template == "exam_weak"]


def test_daily_time_is_respected_when_there_is_room():
    tasks = plan(
        exams=[exam(10), exam(11, "s2", "Physics")],
        assignments=[AssignmentItem("a1", "s1", "Essay", days(9))],
        cards_by_day={days(i): 8 for i in range(0, 10)},
    )
    per_day = Counter()
    for t in tasks:
        per_day[t.day] += t.minutes
    assert max(per_day.values()) <= 90


def test_when_there_is_no_room_the_work_still_gets_scheduled():
    tasks = plan(daily_minutes=20, exams=[exam(4)])
    assert tasks  # over the limit rather than dropped
    assert all(today_ok(t.day) and t.day < days(4) for t in tasks)


# ------------------------------------------------------------------ assignments


def test_an_assignment_due_tomorrow_is_one_long_session_today():
    (task,) = plan(assignments=[AssignmentItem("a", None, "Essay", days(1))])
    assert task.day == TODAY and task.minutes == 60 and task.assignment_id == "a"


def test_an_assignment_due_in_ten_days_gets_plan_write_and_review_in_order():
    tasks = plan(assignments=[AssignmentItem("a", None, "Essay", days(10))])
    by_template = {t.template: t for t in tasks}
    assert set(by_template) == {"assignment_plan", "assignment_write", "assignment_review"}
    assert by_template["assignment_plan"].day <= by_template["assignment_write"].day
    assert by_template["assignment_write"].day <= by_template["assignment_review"].day
    assert by_template["assignment_review"].day == days(9)
    assert all(t.day < days(10) for t in tasks)


def test_an_assignment_already_in_progress_skips_the_planning_session():
    tasks = plan(assignments=[AssignmentItem("a", None, "Essay", days(10), in_progress=True)])
    assert "assignment_plan" not in {t.template for t in tasks}


def test_an_overdue_assignment_gets_a_catch_up_session_today():
    (task,) = plan(assignments=[AssignmentItem("a", None, "Essay", days(-2))])
    assert task.day == TODAY


def test_an_assignment_without_a_due_date_is_not_scheduled():
    assert plan(assignments=[AssignmentItem("a", None, "Essay", None)]) == []


# ------------------------------------------------------------------ weak quizzes


def test_weak_subjects_without_an_exam_get_a_short_quiz_and_at_most_three():
    weak = [WeakSpot(f"s{i}", f"Subject {i}", "f.pdf", 0.1 * (i + 1), 10) for i in range(5)]
    tasks = [t for t in plan(weak=weak) if t.template == "weak_quiz"]
    assert len(tasks) == 3 and all(t.kind == "quiz" and t.minutes == 20 for t in tasks)
    assert [t.params["subject"] for t in sorted(tasks, key=lambda t: t.params["percent"])] == [
        "Subject 0", "Subject 1", "Subject 2",
    ]


def test_a_subject_with_an_exam_is_not_given_a_separate_weak_quiz():
    weak = [WeakSpot("s1", "Biology", "a.pdf", 0.2, 10)]
    tasks = plan(exams=[exam(10)], weak=weak)
    assert not [t for t in tasks if t.template == "weak_quiz"]


def test_subject_accuracy_weights_by_number_of_answers():
    weak = [WeakSpot("s", "Bio", "a", 1.0, 1), WeakSpot("s", "Bio", "b", 0.0, 3)]
    assert subject_accuracy(weak) == {"s": ("Bio", 0.25, 4)}


# ------------------------------------------------------------------ calendar rules


def test_busy_minutes_make_room_elsewhere():
    free = plan(exams=[exam(3)])
    busy = plan(exams=[exam(3)], busy={days(0): 90, days(1): 90})
    assert {t.day for t in free} != {t.day for t in busy}
    assert all(t.day == days(2) for t in busy)


def test_days_off_are_never_used_for_new_sessions():
    off = [days(2).weekday(), days(3).weekday()]
    tasks = plan(days_off=off, exams=[exam(10)], assignments=[AssignmentItem("a", None, "E", days(8))])
    assert tasks and all(t.day.weekday() not in off for t in tasks)


def test_the_same_input_gives_the_same_plan():
    args = dict(exams=[exam(9), exam(12, "s2", "Physics")],
                assignments=[AssignmentItem("a", "s1", "Essay", days(6))],
                cards_by_day={days(1): 6}, weak=[WeakSpot("s1", "Biology", "x.pdf", 0.3, 9)])
    assert plan(**args) == plan(**args)


def test_the_horizon_is_kept_between_a_week_and_four_weeks():
    far = [ExamItem("e", "s", "Bio", days(26))]
    assert plan(exams=far, horizon=1) == []  # one day is raised to seven: exam not in reach
    assert plan(exams=far, horizon=200)  # 200 is cut to 28: the exam is in reach
    assert max(t.day for t in plan(exams=far, horizon=200)) < days(26)


# ------------------------------------------------------------------ wording and dates


def test_every_template_renders_in_english():
    params = {"title": "T", "subject": "S", "name": "n.pdf", "percent": 40, "count": 3}
    for template in TITLES:
        assert render_title(template, params)
    assert render_title("cards_due", params) == "Spaced revision: 3 cards"


def test_today_follows_the_students_time_zone():
    moment = datetime(2026, 11, 2, 21, 0, tzinfo=UTC)  # 02:30 on the 3rd in India
    assert local_today("Asia/Kolkata", moment) == date(2026, 11, 3)
    assert local_today("UTC", moment) == date(2026, 11, 2)
    assert local_today("Not/AZone", moment) == date(2026, 11, 2)


# ------------------------------------------------------------------ keeping what the student decided


def test_each_decided_task_cancels_out_one_new_task_about_the_same_thing():
    new = plan(exams=[ExamItem("e1", "s1", "Biology", days(10))])
    revise = [t for t in new if t.template == "exam_revise"]
    final = [t for t in new if t.template == "exam_final"]
    assert len(revise) >= 3 and len(final) == 1

    decided = [
        task_key("exam_final", "s1", None, "e1", days(9)),
        task_key("exam_revise", "s1", None, "e1", days(3)),  # a different day: still the same session
    ]
    kept, dropped = drop_decided(new, decided)
    assert dropped == 2
    assert not [t for t in kept if t.template == "exam_final"]
    assert len([t for t in kept if t.template == "exam_revise"]) == len(revise) - 1


def test_decided_tasks_about_something_else_change_nothing():
    new = plan(exams=[ExamItem("e1", "s1", "Biology", days(10))])
    kept, dropped = drop_decided(new, [task_key("exam_final", "s1", None, "other-exam", days(9))])
    assert dropped == 0 and kept == new


def test_spaced_revision_is_matched_by_day():
    new = plan(cards_by_day={days(1): 8, days(2): 5})
    kept, dropped = drop_decided(new, [task_key("cards_due", None, None, None, days(1))])
    assert dropped == 1
    assert [t.day for t in kept if t.template == "cards_due"] == [days(2)]


def test_a_day_over_the_limit_is_flagged_with_the_nearest_day_with_room():
    load = {days(1): 130, days(2): 80, days(3): 20}
    (flag,) = find_overloads(load, daily_minutes=100, days_off=[], today=TODAY, last=days(13))
    assert (flag.day, flag.minutes, flag.limit, flag.excess, flag.day_off) == (days(1), 130, 100, 30, False)
    assert flag.suggested == TODAY  # one day away, 100 free, earlier than day 2 (also one away, 20 free)


def test_a_day_exactly_at_the_limit_is_fine_and_past_days_are_ignored():
    load = {days(-2): 300, days(1): 90}
    assert find_overloads(load, daily_minutes=90, days_off=[], today=TODAY, last=days(13)) == []


def test_work_on_a_day_off_is_flagged_and_never_suggested_as_a_destination():
    saturday = days(5)  # TODAY is a Monday
    load = {saturday: 30}
    (flag,) = find_overloads(load, daily_minutes=90, days_off=[5, 6], today=TODAY, last=days(13))
    assert flag.day == saturday and flag.day_off and flag.excess == 30
    assert flag.suggested is not None and flag.suggested.weekday() not in (5, 6)


def test_no_suggestion_when_every_nearby_day_is_full():
    load = {days(i): 100 for i in range(0, 14)}
    flagged = find_overloads(load, daily_minutes=90, days_off=[], today=TODAY, last=days(13))
    assert len(flagged) == 14 and all(f.suggested is None for f in flagged)
