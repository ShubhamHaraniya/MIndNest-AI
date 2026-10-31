"""Quiz status, the "card is due" rule and the question checks."""

from datetime import UTC, datetime

from mindnest_core.quizcheck import Candidate, QuestionChecker, find_duplicates, primary_issue
from mindnest_core.quizlogic import card_is_due, quiz_display_status


def shown(status="ready", archived=False, open_attempt=False, submitted=0):  # type: ignore[no-untyped-def]
    return quiz_display_status(
        status=status, archived=archived, open_attempt=open_attempt, submitted_attempts=submitted
    )


def test_a_new_quiz_is_ready_then_in_progress_then_completed():
    assert shown() == "ready"
    assert shown(open_attempt=True) == "in_progress"
    assert shown(submitted=2) == "completed"
    # An open retake wins over earlier finished attempts.
    assert shown(open_attempt=True, submitted=2) == "in_progress"


def test_archived_wins_over_everything_else():
    assert shown(archived=True, open_attempt=True, submitted=3) == "archived"
    assert shown(status="failed", archived=True) == "archived"


def test_a_quiz_that_is_not_written_yet_is_preparing_and_a_broken_one_is_failed():
    assert shown(status="queued") == "preparing"
    assert shown(status="generating", open_attempt=True) == "preparing"
    assert shown(status="failed") == "failed"


def test_a_card_is_due_on_its_day_in_the_students_time_zone():
    now = datetime(2026, 10, 27, 23, 0, tzinfo=UTC)  # 04:30 on the 28th in India
    due = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)  # 08:30 on the 28th in India
    assert card_is_due(due, now, "Asia/Kolkata")  # the same day there, so due
    assert not card_is_due(due, now, "UTC")  # tomorrow in UTC
    assert card_is_due(datetime(2026, 10, 20, tzinfo=UTC), now, "UTC")  # earlier days stay due


def test_a_card_of_an_archived_course_is_never_due():
    moment = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    assert card_is_due(moment, moment, "UTC")
    assert not card_is_due(moment, moment, "UTC", subject_archived=True)


def mcq(prompt="What is the powerhouse of the cell?", options=None, answer="1"):  # type: ignore[no-untyped-def]
    options = options if options is not None else ["Nucleus", "Mitochondria", "Ribosome", "Golgi body"]
    return Candidate(qtype="mcq", prompt=prompt, options=options, answer=answer)


def test_a_good_question_has_no_issues():
    assert QuestionChecker().check(mcq()) == []


def test_an_answer_outside_the_options_is_rejected():
    assert primary_issue(QuestionChecker().check(mcq(answer="9"))) == "answer_not_in_options"


def test_options_must_be_distinct_and_filled_in():
    issues = QuestionChecker().check(mcq(options=["Same", "Same", "Other", "Another"]))
    assert "duplicate_options" in issues
    assert "option_empty" in QuestionChecker().check(mcq(options=["A one", "", "C three", "D four"]))


def test_a_repeated_question_is_rejected_even_with_different_punctuation():
    checker = QuestionChecker()
    assert checker.admit(mcq()) == []
    assert "duplicate_question" in checker.admit(mcq(prompt="what is the POWERHOUSE of the cell"))


def test_a_rejected_question_can_be_asked_again_later():
    checker = QuestionChecker()
    assert checker.admit(mcq(answer="9")) != []
    assert checker.admit(mcq()) == []


def test_true_false_needs_a_plain_true_or_false():
    ok = Candidate(qtype="true_false", prompt="Plants make oxygen by photosynthesis.", answer="true")
    bad = Candidate(qtype="true_false", prompt="Plants make oxygen by photosynthesis.", answer="maybe")
    assert QuestionChecker().check(ok) == []
    assert QuestionChecker().check(bad) == ["answer_invalid"]


def test_a_short_question_needs_a_model_answer_and_no_options():
    assert QuestionChecker().check(Candidate(qtype="short", prompt="Define osmosis in one line.", answer="")) == ["answer_missing"]
    with_options = Candidate(qtype="short", prompt="Define osmosis in one line.", options=["a"], answer="Movement of water")
    assert QuestionChecker().check(with_options) == ["unexpected_options"]


def test_duplicates_are_found_by_position_and_the_first_is_kept():
    assert find_duplicates(["Alpha beta?", "Gamma?", "alpha  BETA"]) == [2]
