"""Working out what to put on the student's Google Calendar."""

from datetime import date, timedelta

from mindnest_core.calsync import (
    LABELS,
    MAX_SYNC_ITEMS,
    Candidate,
    Synced,
    diff,
    event_body,
    summary_for,
)

TODAY = date(2026, 11, 10)


def cand(kind="exam", ident="a", offset=5, summary="Exam: Midterm", description=""):
    return Candidate(kind, ident, TODAY + timedelta(days=offset), summary, description)


def sent(candidate, event_id="ev1"):
    return Synced(candidate.day, candidate.fingerprint, event_id)


def test_a_new_item_is_a_create():
    c = cand()
    changes = diff([c], {}, TODAY)
    assert [(x.action, x.source_id, x.event_id) for x in changes] == [("create", "a", None)]
    assert changes[0].candidate == c


def test_an_item_already_sent_and_unchanged_is_left_alone():
    c = cand()
    assert diff([c], {c.key: sent(c)}, TODAY) == []


def test_a_changed_title_or_day_is_an_update_that_keeps_the_event_id():
    old = cand()
    renamed = cand(summary="Exam: Final")
    moved = cand(offset=9)
    for new in (renamed, moved):
        (change,) = diff([new], {old.key: sent(old, "ev9")}, TODAY)
        assert change.action == "update" and change.event_id == "ev9"
        assert change.candidate == new


def test_an_item_no_longer_wanted_is_a_delete():
    old = cand()
    (change,) = diff([], {old.key: sent(old, "ev3")}, TODAY)
    assert change.action == "delete" and change.event_id == "ev3" and change.candidate is None
    assert change.day == old.day


def test_events_for_days_already_past_are_not_deleted():
    past = cand(offset=-2)
    assert diff([], {past.key: sent(past)}, TODAY) == []


def test_today_still_counts():
    today = cand(offset=0)
    assert [c.action for c in diff([], {today.key: sent(today)}, TODAY)] == ["delete"]


def test_the_same_id_under_a_different_kind_is_a_different_item():
    exam, task = cand("exam", "x"), cand("task", "x")
    changes = diff([exam, task], {exam.key: sent(exam)}, TODAY)
    assert [(c.action, c.source_type) for c in changes] == [("create", "task")]


def test_changes_come_back_in_date_order():
    late, early = cand(ident="l", offset=20), cand(ident="e", offset=2)
    assert [c.source_id for c in diff([late, early], {}, TODAY)] == ["e", "l"]


def test_the_fingerprint_follows_what_the_student_sees():
    assert cand().fingerprint == cand().fingerprint
    assert cand().fingerprint != cand(summary="Exam: Other").fingerprint
    assert cand().fingerprint != cand(offset=6).fingerprint
    assert cand().fingerprint != cand(description="notes").fingerprint


def test_summaries_use_the_students_language_and_minutes():
    assert summary_for("en", "exam", "  Biology ") == "Exam: Biology"
    assert summary_for("en", "task", "Revise", 45) == "Study: Revise (45 min)"
    assert summary_for("hi", "exam", "जीव विज्ञान").startswith(LABELS["hi"]["exam"])
    assert summary_for("gu", "assignment", "Essay").startswith(LABELS["gu"]["assignment"])
    assert summary_for("fr", "exam", "Biology") == "Exam: Biology"  # unknown language falls back
    assert len(summary_for("en", "task", "x" * 500)) == 200


def test_every_language_labels_every_kind():
    for language in LABELS.values():
        assert set(language) == {"exam", "assignment", "task"}


def test_the_event_is_all_day_ends_the_next_day_and_does_not_block_time():
    c = cand("assignment", "abc", offset=3, summary="Due: Essay")
    body = event_body(c, "https://app.example/planner")
    assert body["start"] == {"date": c.day.isoformat()}
    assert body["end"] == {"date": (c.day + timedelta(days=1)).isoformat()}
    assert body["transparency"] == "transparent"
    assert body["summary"] == "Due: Essay"
    assert body["description"] == "https://app.example/planner"
    assert body["extendedProperties"]["private"] == {"mindnest": "1", "source": "assignment", "id": "abc"}


def test_the_description_keeps_notes_then_the_link():
    body = event_body(cand(description="Chapters 3-4"), "https://x.example/")
    assert body["description"] == "Chapters 3-4\n\nhttps://x.example/"


def test_the_limit_is_sane():
    assert 10 <= MAX_SYNC_ITEMS <= 100


# ------------------------------------------------------------------ the student's own events


def own_event(**overrides):
    args = {"start_time": "16:00", "minutes": 45, "timezone": "Asia/Kolkata", "transparent": False}
    args.update(overrides)
    return Candidate("event", "e1", TODAY + timedelta(days=3), "Dentist", "Bring the form", **args)


def test_an_event_is_sent_with_its_time_and_blocks_it():
    from mindnest_core.calsync import event_in

    body = event_in(own_event(), "https://app.example/calendar")
    assert (body.start_time, body.minutes, body.timezone, body.transparent) == ("16:00", 45, "Asia/Kolkata", False)
    assert body.description.endswith("https://app.example/calendar") and "Bring the form" in body.description


def test_exams_and_tasks_are_still_all_day_markers_that_do_not_block_time():
    from mindnest_core.calsync import event_in

    body = event_in(cand(), "https://app.example/planner")
    assert body.all_day and body.transparent


def test_changing_an_events_time_or_length_changes_its_fingerprint():
    base = own_event().fingerprint
    assert base == own_event().fingerprint
    assert base != own_event(start_time="17:00").fingerprint
    assert base != own_event(minutes=60).fingerprint
    assert base != own_event(timezone="UTC").fingerprint
    assert base != own_event(transparent=True).fingerprint


def test_the_fingerprints_of_other_kinds_ignore_the_time_fields():
    # Items sent before events existed must not look changed.
    assert cand().fingerprint == Candidate("exam", "a", TODAY + timedelta(days=5), "Exam: Midterm", "").fingerprint
    assert cand().fingerprint == Candidate(
        "exam", "a", TODAY + timedelta(days=5), "Exam: Midterm", "", start_time="09:00", minutes=5
    ).fingerprint


def test_the_request_key_names_one_version_of_one_item():
    first = own_event()
    assert first.request_key == own_event().request_key
    assert first.request_key != own_event(start_time="17:00").request_key
    assert first.request_key != Candidate("task", "e1", first.day, "Dentist", "Bring the form").request_key
    assert first.request_key.startswith("gcal:event:e1:")


def test_an_event_that_is_no_longer_wanted_is_removed_from_google():
    wanted = own_event()
    changes = diff([], {wanted.key: sent(wanted)}, TODAY)
    assert [(c.action, c.source_type) for c in changes] == [("delete", "event")]
