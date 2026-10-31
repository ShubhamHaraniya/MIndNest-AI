"""Events in MindNest's shape and in Google's."""

from datetime import date

import pytest
from mindnest_core.calevent import EventIn, Op, google_body, read_event
from pydantic import ValidationError


def test_an_event_without_a_time_is_all_day_and_ends_the_next_day():
    body = google_body(EventIn(summary="Exam", day=date(2026, 12, 31)))
    assert body["start"] == {"date": "2026-12-31"} and body["end"] == {"date": "2027-01-01"}


def test_a_timed_event_carries_its_zone_and_length():
    body = google_body(EventIn(summary="Study", day=date(2026, 11, 3), start_time="23:30", minutes=90,
                               timezone="Asia/Kolkata"))
    assert body["start"] == {"dateTime": "2026-11-03T23:30:00", "timeZone": "Asia/Kolkata"}
    assert body["end"] == {"dateTime": "2026-11-04T01:00:00", "timeZone": "Asia/Kolkata"}


def test_events_are_marked_as_made_by_mindnest():
    body = google_body(EventIn(summary="x", day=date(2026, 1, 1), source_type="exam", source_id="abc-1"))
    assert body["extendedProperties"]["private"] == {"mindnest": "1", "source": "exam", "id": "abc-1"}
    assert google_body(EventIn(summary="x", day=date(2026, 1, 1), transparent=True))["transparency"] == "transparent"


@pytest.mark.parametrize(
    "bad",
    [
        {"summary": ""}, {"summary": "x" * 201}, {"start_time": "25:00"}, {"start_time": "9:00"},
        {"minutes": 1}, {"minutes": 5000}, {"timezone": "Mars/Base"}, {"source_id": "a b"},
        {"unknown_field": 1},
    ],
)
def test_bad_input_is_refused(bad):
    with pytest.raises(ValidationError):
        EventIn(**{"summary": "x", "day": date(2026, 1, 1), **bad})


def test_what_google_returns_is_reduced_to_what_we_show():
    raw = {
        "id": "e1", "summary": "Study", "status": "confirmed", "htmlLink": "https://calendar.google.com/x",
        "start": {"dateTime": "2026-11-03T18:30:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-11-03T19:15:00+05:30"},
        "extendedProperties": {"private": {"mindnest": "1"}},
    }
    event = read_event(raw)
    assert (event["day"], event["start_time"], event["minutes"], event["all_day"]) == ("2026-11-03", "18:30", 45, False)
    assert event["link"] == "https://calendar.google.com/x" and event["mindnest"] is True
    assert read_event({"id": "e2", "start": {"date": "2026-11-03"}})["all_day"] is True


def test_a_batch_change_holds_at_most_one_event():
    assert Op(action="delete", event_id="e").event is None
    with pytest.raises(ValidationError):
        Op(action="explode")  # type: ignore[arg-type]


def test_a_create_can_carry_a_request_key_and_it_has_a_limit():
    event = EventIn(summary="x", day=date(2026, 1, 1))
    assert Op(action="create", event=event).request_key == ""
    assert Op(action="create", event=event, request_key="gcal:event:1:abc").request_key == "gcal:event:1:abc"
    with pytest.raises(ValidationError):
        Op(action="create", event=event, request_key="k" * 201)
