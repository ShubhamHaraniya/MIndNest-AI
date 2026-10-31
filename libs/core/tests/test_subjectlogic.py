"""Course progress, list ordering, module ordering, coverage and recommendations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from mindnest_core.subjectlogic import (
    Deadline,
    ProgressInputs,
    Signals,
    WeakTopic,
    accuracy_trend,
    check_reorder,
    clean_module_name,
    clean_optional_label,
    clean_topics,
    course_progress,
    material_coverage,
    move_item,
    name_key,
    natural_key,
    next_position,
    progress_parts,
    recommend_next,
    share,
    sort_courses,
)

# ----------------------------------------------------------------------------------- progress


def test_progress_is_not_measured_when_only_uploads_exist():
    assert course_progress(ProgressInputs()) is None
    # Every file read, but nothing practised and no tasks: still nothing learned to report.
    assert course_progress(ProgressInputs(documents=4, documents_ready=4)) is None


def test_progress_uses_all_three_signals_with_their_weights():
    inputs = ProgressInputs(
        documents=10, documents_ready=5, quiz_attempts=2, quiz_accuracy=0.8, tasks_total=4, tasks_done=1
    )
    # 0.3 * 0.5 + 0.5 * 0.8 + 0.2 * 0.25
    assert course_progress(inputs) == pytest.approx(0.6)


def test_missing_signals_share_their_weight_among_the_others():
    only_quizzes = ProgressInputs(quiz_attempts=1, quiz_accuracy=0.9)
    assert course_progress(only_quizzes) == pytest.approx(0.9)
    quizzes_and_tasks = ProgressInputs(quiz_attempts=3, quiz_accuracy=0.5, tasks_total=2, tasks_done=2)
    # weights 0.5 / 0.7 and 0.2 / 0.7
    assert course_progress(quizzes_and_tasks) == pytest.approx(0.5 * 5 / 7 + 1.0 * 2 / 7, abs=1e-3)


def test_effective_weights_add_up_to_one_when_anything_is_present():
    parts = progress_parts(ProgressInputs(documents=2, documents_ready=1, tasks_total=3, tasks_done=1))
    assert sum(p.weight for p in parts) == pytest.approx(1.0, abs=1e-3)
    assert {p.key: p.value for p in parts}["quizzes"] is None
    assert {p.key: p.weight for p in parts}["quizzes"] == 0


def test_an_attempt_without_a_score_does_not_count_as_a_quiz_signal():
    assert course_progress(ProgressInputs(documents=1, documents_ready=1, quiz_attempts=1, quiz_accuracy=None)) is None


def test_progress_is_clamped_to_zero_and_one():
    high = ProgressInputs(quiz_attempts=1, quiz_accuracy=1.7)
    low = ProgressInputs(quiz_attempts=1, quiz_accuracy=-0.2)
    assert course_progress(high) == 1.0
    assert course_progress(low) == 0.0


def test_zero_accuracy_is_progress_zero_not_missing():
    assert course_progress(ProgressInputs(quiz_attempts=2, quiz_accuracy=0.0)) == 0.0


# ------------------------------------------------------------------------------ ordering


@dataclass
class Row:
    name: str
    semester: str | None = None
    last_activity_at: datetime | None = None
    progress: float | None = None


NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def names(rows):
    return [r.name for r in rows]


def test_natural_key_puts_unit_2_before_unit_10():
    assert sorted(["Unit 10", "unit 2", "Unit 1"], key=natural_key) == ["Unit 1", "unit 2", "Unit 10"]


def test_sort_by_name_is_natural_and_can_be_reversed():
    rows = [Row("Sem 10 Lab"), Row("sem 2 Lab"), Row("Algorithms")]
    assert names(sort_courses(rows, "name")) == ["Algorithms", "sem 2 Lab", "Sem 10 Lab"]
    assert names(sort_courses(rows, "name", descending=True)) == ["Sem 10 Lab", "sem 2 Lab", "Algorithms"]


def test_sort_by_recent_activity_puts_never_active_courses_last_either_way():
    rows = [
        Row("Old", last_activity_at=NOW - timedelta(days=9)),
        Row("None"),
        Row("New", last_activity_at=NOW),
    ]
    assert names(sort_courses(rows, "recent")) == ["New", "Old", "None"]
    assert names(sort_courses(rows, "recent", descending=False)) == ["Old", "New", "None"]


def test_sort_by_progress_puts_unmeasured_courses_last_either_way():
    rows = [Row("A", progress=0.2), Row("B"), Row("C", progress=0.9), Row("D", progress=0.0)]
    assert names(sort_courses(rows, "progress")) == ["C", "A", "D", "B"]
    assert names(sort_courses(rows, "progress", descending=False)) == ["D", "A", "C", "B"]


def test_sort_by_semester_is_numeric_aware_and_keeps_unset_last():
    rows = [Row("A", "Sem 10"), Row("B", "Sem 2"), Row("C"), Row("D", "Sem 2")]
    assert names(sort_courses(rows, "semester")) == ["B", "D", "A", "C"]
    assert names(sort_courses(rows, "semester", descending=True)) == ["A", "B", "D", "C"]


def test_ties_break_on_name_and_unknown_sorts_are_refused():
    rows = [Row("Zeta", progress=0.5), Row("Alpha", progress=0.5)]
    assert names(sort_courses(rows, "progress")) == ["Alpha", "Zeta"]
    with pytest.raises(ValueError):
        sort_courses(rows, "popularity")


# -------------------------------------------------------------------------------- modules


def test_module_names_are_tidied_and_bounded():
    assert clean_module_name("  Unit   2 — Processes ") == "Unit 2 — Processes"
    with pytest.raises(ValueError):
        clean_module_name("   ")
    with pytest.raises(ValueError):
        clean_module_name("x" * 81)
    assert clean_module_name("x" * 80) == "x" * 80


def test_optional_labels_blank_to_none():
    assert clean_optional_label(None) is None
    assert clean_optional_label("   ") is None
    assert clean_optional_label(" Chapter  3 ") == "Chapter 3"
    with pytest.raises(ValueError):
        clean_optional_label("y" * 81)


def test_module_names_that_differ_only_in_case_or_spacing_match():
    assert name_key("Unit  1") == name_key("unit 1 ")
    assert name_key("Unit 1") != name_key("Unit 2")


def test_topics_are_deduplicated_ignoring_case_and_keep_their_order():
    assert clean_topics(["Deadlock", "  paging ", "deadlock", "", "Paging", "Scheduling"]) == [
        "Deadlock",
        "paging",
        "Scheduling",
    ]
    with pytest.raises(ValueError):
        clean_topics(["t" * 81])
    with pytest.raises(ValueError):
        clean_topics([f"topic {i}" for i in range(41)])


def test_move_item_up_down_top_bottom_and_stops_at_the_ends():
    order = ["a", "b", "c", "d"]
    assert move_item(order, "c", "up") == ["a", "c", "b", "d"]
    assert move_item(order, "b", "down") == ["a", "c", "b", "d"]
    assert move_item(order, "d", "top") == ["d", "a", "b", "c"]
    assert move_item(order, "a", "bottom") == ["b", "c", "d", "a"]
    assert move_item(order, "a", "up") == order
    assert move_item(order, "d", "down") == order
    assert order == ["a", "b", "c", "d"]  # the input is not changed
    with pytest.raises(ValueError):
        move_item(order, "z", "up")


def test_a_reorder_must_be_a_permutation_of_the_current_list():
    check_reorder(["a", "b", "c"], ["c", "a", "b"])
    with pytest.raises(ValueError):
        check_reorder(["a", "b", "c"], ["a", "b"])  # one missing
    with pytest.raises(ValueError):
        check_reorder(["a", "b"], ["a", "b", "c"])  # one invented
    with pytest.raises(ValueError):
        check_reorder(["a", "b"], ["a", "a"])  # repeated


def test_next_position_appends_after_the_last_one():
    assert next_position([]) == 0
    assert next_position([0, 1, 2]) == 3
    assert next_position([4, 1]) == 5


# -------------------------------------------------------------------------------- coverage


def test_coverage_counts_files_read_files_practised_and_modules():
    files = [
        ("a.pdf", "Unit 1", "ready"),
        ("b.pdf", "Unit 1", "ready"),
        ("c.pdf", "Unit 2", "ready"),
        ("d.pdf", None, "failed"),
        ("e.pdf", "unit 3", "processing"),
    ]
    coverage = material_coverage(files, {"a.pdf", "c.pdf", "d.pdf"}, listed_modules=["Unit 1", "Unit 4"])
    assert coverage.documents == 5
    assert coverage.documents_ready == 3
    assert coverage.documents_practised == 2  # d.pdf is not ready
    # Unit 1, Unit 4 (listed, empty), Unit 2, unit 3
    assert coverage.modules_total == 4
    assert coverage.modules_with_files == 3
    assert coverage.modules_practised == 2  # Unit 1 (a.pdf) and Unit 2 (c.pdf)


def test_listed_module_and_file_label_with_different_case_are_one_module():
    coverage = material_coverage([("a.pdf", "unit 1", "ready")], set(), listed_modules=["Unit 1"])
    assert coverage.modules_total == 1
    assert coverage.modules_with_files == 1
    assert coverage.modules_practised == 0


def test_empty_course_coverage_is_all_zero():
    coverage = material_coverage([], set())
    assert (coverage.documents, coverage.modules_total, coverage.documents_practised) == (0, 0, 0)


def test_share_is_none_without_a_denominator():
    assert share(1, 0) is None
    assert share(1, 4) == 0.25


def test_trend_needs_four_attempts_and_a_five_point_change():
    assert accuracy_trend([0.2, 0.9, 0.9]) is None
    assert accuracy_trend([0.4, 0.5, 0.7, 0.8]) == "improving"
    assert accuracy_trend([0.9, 0.8, 0.6, 0.5]) == "declining"
    assert accuracy_trend([0.6, 0.62, 0.61, 0.63]) == "steady"
    # With an odd count the middle attempt belongs to neither half.
    assert accuracy_trend([0.2, 0.2, 0.9, 0.9, 0.9]) == "improving"


# --------------------------------------------------------------------------- recommendations


def test_no_signals_means_no_recommendations_except_adding_files():
    assert recommend_next(Signals(materials=3, ready_materials=3, quiz_attempts=2)) == []
    only = recommend_next(Signals())
    assert [r.kind for r in only] == ["upload_first"]


def test_overdue_assignment_comes_before_everything_else():
    signals = Signals(
        weak_topics=[WeakTopic("Paging", 0.1, 5)],
        revision_due=12,
        deadlines=[
            Deadline("exam", "e1", "Midterm", 2),
            Deadline("assignment", "a1", "Lab report", -1),
        ],
        materials=2,
        ready_materials=2,
        quiz_attempts=1,
    )
    kinds = [(r.kind, r.label) for r in recommend_next(signals)]
    assert kinds[0] == ("deadline", "Lab report")
    assert kinds[1] == ("deadline", "Midterm")
    assert ("weak_topic", "Paging") in kinds
    assert any(kind == "revision_due" for kind, _ in kinds)


def test_far_off_and_past_exams_are_not_recommended():
    signals = Signals(
        deadlines=[Deadline("exam", "e1", "Final", 60), Deadline("exam", "e2", "Old", -4)],
        materials=1,
        ready_materials=1,
        quiz_attempts=1,
    )
    assert recommend_next(signals) == []


def test_weaker_topics_rank_higher_and_carry_their_numbers():
    signals = Signals(
        weak_topics=[WeakTopic("Mild", 0.6, 4, "m1"), WeakTopic("Bad", 0.2, 6, "m2")],
        materials=2,
        ready_materials=2,
        quiz_attempts=1,
    )
    result = recommend_next(signals)
    assert [r.label for r in result] == ["Bad", "Mild"]
    assert result[0].ref_id == "m2"
    assert result[0].params == {"accuracy": 0.2, "answers": 6}


def test_revision_cards_and_failed_files_and_first_quiz_are_suggested_from_real_counts():
    signals = Signals(revision_due=9, failed_materials=2, ready_materials=3, materials=5, quiz_attempts=0)
    result = {r.kind: r for r in recommend_next(signals)}
    assert result["revision_due"].params == {"count": 9}
    assert result["retry_failed"].params == {"count": 2}
    assert "first_quiz" in result
    assert "upload_first" not in result


def test_first_quiz_is_not_suggested_when_the_student_already_took_one():
    result = recommend_next(Signals(ready_materials=3, materials=3, quiz_attempts=1))
    assert result == []


def test_limit_caps_the_list_and_zero_gives_nothing():
    signals = Signals(
        weak_topics=[WeakTopic(f"T{i}", 0.3, 4) for i in range(10)], materials=1, ready_materials=1, quiz_attempts=1
    )
    assert len(recommend_next(signals)) == 6
    assert len(recommend_next(signals, limit=2)) == 2
    assert recommend_next(signals, limit=0) == []


def test_deadline_priority_falls_as_the_date_moves_away():
    signals = Signals(
        deadlines=[Deadline("exam", "a", "Soon", 1), Deadline("exam", "b", "Week", 6), Deadline("exam", "c", "Later", 15)],
        materials=1,
        ready_materials=1,
        quiz_attempts=1,
    )
    assert [r.label for r in recommend_next(signals)] == ["Soon", "Week", "Later"]
