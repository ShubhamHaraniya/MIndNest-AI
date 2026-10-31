"""What the planner and the Calendar page need beyond the basics: where a task belongs, and the
student's own Google events."""

from .test_assignments import sql
from .test_gcal import add_assignment, add_exam, add_task, connect, day, send, preview


def test_calendar_tasks_say_what_they_belong_to_and_assignments_carry_their_time(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    exam_id = add_exam(user, 8, "Midterm")
    assignment_id = add_assignment(user, 4, "Essay")
    plan = user.post("/planner/generate", json={"days": 14}).json()
    assert plan["created"] > 0
    own = add_task(user, 1, "My own task")

    events = user.get("/calendar", params={"from": day(0), "to": day(14)}).json()["events"]
    tasks = [e for e in events if e["kind"] == "task"]
    planned = [t for t in tasks if t["source"] == "plan"]
    assert any(t["exam_id"] == exam_id for t in planned)
    assert any(t["assignment_id"] == assignment_id for t in planned)
    mine = next(t for t in tasks if t["id"] == own)
    assert mine["source"] == "manual" and mine["exam_id"] is None and mine["assignment_id"] is None
    essay = next(e for e in events if e["kind"] == "assignment")
    assert essay["due_at"] is not None and essay["status"] == "todo"
    assert next(e for e in events if e["kind"] == "exam")["exam_id"] is None


def test_google_events_are_empty_until_calendar_is_connected(make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    answer = user.get("/calendar/google", params={"from": day(0), "to": day(30)})
    assert answer.status_code == 200
    assert answer.json() == {"connected": False, "error": None, "events": []}
    assert user.get("/calendar/google", params={"from": day(5), "to": day(1)}).status_code == 422
    assert user.get("/calendar/google", params={"from": day(0), "to": day(100)}).status_code == 422
    assert user.get("/calendar/google", params={"from": day(0)}).status_code == 422


def test_only_events_that_are_not_already_on_the_page_are_listed(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 3, "Midterm")
    add_task(user, 2, "Revise cells")
    # What MindNest sent from its own records is shown from those records, not twice.
    assert send(user, [{"source_type": c["source_type"], "source_id": c["source_id"]} for c in preview(user)]).status_code == 200
    assert len(calendar_api.events) == 2
    # An event somebody added straight to the calendar (or the chat assistant did).
    calendar_api.events["manual1"] = {
        "summary": "Lab viva", "start": {"dateTime": f"{day(3)}T10:30:00+05:30"},
        "end": {"dateTime": f"{day(3)}T11:15:00+05:30"},
    }
    calendar_api.events["far"] = {"summary": "Next month", "start": {"date": day(45)}, "end": {"date": day(46)}}

    answer = user.get("/calendar/google", params={"from": day(0), "to": day(30)}).json()
    assert answer["connected"] is True and answer["error"] is None
    assert [(e["summary"], e["day"], e["start_time"], e["minutes"], e["all_day"]) for e in answer["events"]] == [
        ("Lab viva", day(3), "10:30", 45, False)
    ]
    assert answer["events"][0]["link"].startswith("https://calendar.google.com/")


def test_google_trouble_does_not_break_the_page(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    calendar_api.fail["list"] = 500
    answer = user.get("/calendar/google", params={"from": day(0), "to": day(7)}).json()
    assert answer["connected"] is True and answer["events"] == [] and answer["error"]
    calendar_api.fail.clear()
    sql("UPDATE google_calendar_links SET needs_reconnect = true WHERE user_id = :u", u=user.id)
    answer = user.get("/calendar/google", params={"from": day(0), "to": day(7)}).json()
    assert answer == {"connected": True, "error": "gcal_reconnect", "events": []}


def test_another_student_never_sees_the_events(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    connect(client, owner, google)
    calendar_api.events["m"] = {"summary": "Private", "start": {"date": day(1)}, "end": {"date": day(2)}}
    assert other.get("/calendar/google", params={"from": day(0), "to": day(7)}).json()["events"] == []
    assert len(owner.get("/calendar/google", params={"from": day(0), "to": day(7)}).json()["events"]) == 1
