"""Events the student adds to the calendar, and keeping Google Calendar in step with them."""

import uuid

from .test_gcal import BASE, add_exam, connect, day, preview, send, sql


def add_event(user, title="Physics lab", offset=2, **extra):  # type: ignore[no-untyped-def]
    response = user.post("/calendar/events", json={"title": title, "day": day(offset), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def events_on(user, first=0, last=14):  # type: ignore[no-untyped-def]
    answer = user.get("/calendar", params={"from": day(first), "to": day(last)})
    assert answer.status_code == 200, answer.text
    return [e for e in answer.json()["events"] if e["kind"] == "event"]


def state(user):  # type: ignore[no-untyped-def]
    response = user.get(f"{BASE}/state")
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ adding, changing and removing


def test_an_event_can_be_added_changed_and_removed(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    made = add_event(user, "Physics lab", 2, start_time="14:30", minutes=90, notes="Bring the goggles")
    assert (made["title"], made["day"], made["start_time"], made["minutes"]) == ("Physics lab", day(2), "14:30", 90)
    assert made["sync_to_google"] is False and made["sync"] is None

    (listed,) = events_on(user)
    assert listed["id"] == made["id"] and listed["start_time"] == "14:30" and listed["notes"] == "Bring the goggles"

    changed = user.patch(f"/calendar/events/{made['id']}", json={"day": day(3), "start_time": "", "minutes": 30}).json()
    assert changed["day"] == day(3) and changed["start_time"] == "" and changed["minutes"] == 30
    assert user.delete(f"/calendar/events/{made['id']}").status_code == 204
    assert events_on(user) == []
    assert user.delete(f"/calendar/events/{made['id']}").status_code == 404
    assert user.patch(f"/calendar/events/{made['id']}", json={"title": "x"}).status_code == 404


def test_an_event_can_belong_to_a_course(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = user.post("/subjects", json={"name": "Physics"}).json()["id"]
    made = add_event(user, "Lecture", 1, subject_id=subject_id)
    assert made["subject_id"] == subject_id and made["subject_name"] == "Physics"
    assert events_on(user)[0]["subject_name"] == "Physics"
    cleared = user.patch(f"/calendar/events/{made['id']}", json={"subject_id": None}).json()
    assert cleared["subject_id"] is None
    refused = user.post("/calendar/events", json={"title": "x", "day": day(1), "subject_id": str(uuid.uuid4())})
    assert refused.status_code == 404


def test_bad_event_input_is_refused(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    good = {"title": "Lab", "day": day(1)}
    for bad in (
        {**good, "title": "  "},
        {**good, "title": "x" * 201},
        {**good, "day": "tomorrow"},
        {**good, "start_time": "25:00"},
        {**good, "start_time": "9:30"},
        {**good, "minutes": 2},
        {**good, "minutes": 5000},
        {**good, "request_key": "no"},
        {**good, "notes": "n" * 1001},
    ):
        assert user.post("/calendar/events", json=bad).status_code == 422, bad
    made = add_event(user)
    for bad_patch in ({"title": None}, {"day": None}, {"start_time": "late"}, {"minutes": 1}):
        assert user.patch(f"/calendar/events/{made['id']}", json=bad_patch).status_code == 422, bad_patch


def test_the_same_request_twice_adds_one_event(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    key = "req-" + uuid.uuid4().hex[:12]
    first = add_event(user, "Seminar", 4, request_key=key)
    again = user.post("/calendar/events", json={"title": "Seminar", "day": day(4), "request_key": key})
    assert again.status_code == 201 and again.json()["id"] == first["id"]
    assert len(events_on(user)) == 1


def test_two_events_with_the_same_name_at_the_same_time_are_refused(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    first = add_event(user, "Lab", 2, start_time="10:00")
    twin = user.post("/calendar/events", json={"title": "LAB", "day": day(2), "start_time": "10:00"})
    assert twin.status_code == 409 and twin.json()["code"] == "event_duplicate"
    later = add_event(user, "Lab", 2, start_time="15:00")  # another time is another event
    assert user.patch(f"/calendar/events/{later['id']}", json={"start_time": "10:00"}).status_code == 409
    assert user.patch(f"/calendar/events/{first['id']}", json={"notes": "same event, new note"}).status_code == 200
    assert len(events_on(user)) == 2


def test_one_student_cannot_see_or_change_anothers_events(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    made = add_event(owner, "Private", 2)
    assert events_on(other) == []
    assert other.patch(f"/calendar/events/{made['id']}", json={"title": "mine"}).status_code == 404
    assert other.delete(f"/calendar/events/{made['id']}").status_code == 404
    add_event(other, "Private", 2)  # the same name is fine for somebody else
    assert [e["id"] for e in events_on(owner)] == [made["id"]]


def test_events_sit_in_time_order_on_their_day_with_all_day_first(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_event(user, "Evening", 2, start_time="18:00")
    add_event(user, "Morning", 2, start_time="08:00")
    add_event(user, "All day", 2)
    assert [e["title"] for e in events_on(user)] == ["All day", "Morning", "Evening"]


# ------------------------------------------------------------------ sending to Google


def test_only_events_marked_for_google_are_offered(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_event(user, "Private note", 2)
    wanted = add_event(user, "Dentist", 3, start_time="16:00", minutes=45, sync_to_google=True)
    assert wanted["sync"] == "pending"
    changes = preview(user)
    assert [(c["action"], c["source_type"], c["source_id"], c["summary"]) for c in changes] == [
        ("create", "event", wanted["id"], "Dentist")
    ]


def test_a_timed_event_goes_to_google_at_its_time_and_blocks_it(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, start_time="16:00", minutes=45, notes="Bring the form", sync_to_google=True)
    assert send(user, [{"source_type": "event", "source_id": made["id"]}]).json()["created"] == 1
    (body,) = calendar_api.events.values()
    assert body["summary"] == "Dentist"
    assert body["start"]["dateTime"] == f"{day(3)}T16:00:00" and body["end"]["dateTime"] == f"{day(3)}T16:45:00"
    assert body["transparency"] == "opaque"
    assert body["extendedProperties"]["private"]["source"] == "event"
    assert "Bring the form" in body["description"] and "/calendar" in body["description"]
    assert events_on(user)[0]["sync"] == "synced"
    assert state(user) == {"synced": 1, "pending": 0, "failed": 0, "items": []}


def test_an_all_day_event_does_not_block_time_on_google(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Field trip", 5, sync_to_google=True)
    send(user, [{"source_type": "event", "source_id": made["id"]}])
    (body,) = calendar_api.events.values()
    assert body["start"] == {"date": day(5)} and body["end"] == {"date": day(6)}


def test_changing_an_event_updates_google_and_deleting_it_removes_it(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, start_time="16:00", sync_to_google=True)
    ref = [{"source_type": "event", "source_id": made["id"]}]
    send(user, ref)
    user.patch(f"/calendar/events/{made['id']}", json={"start_time": "17:30"})
    assert [(c["action"], c["source_type"]) for c in preview(user)] == [("update", "event")]
    assert events_on(user)[0]["sync"] == "pending"
    assert send(user, ref).json()["updated"] == 1
    assert next(iter(calendar_api.events.values()))["start"]["dateTime"] == f"{day(3)}T17:30:00"

    user.delete(f"/calendar/events/{made['id']}")
    assert [(c["action"], c["source_type"]) for c in preview(user)] == [("delete", "event")]
    assert send(user, ref).json()["deleted"] == 1
    assert calendar_api.events == {}
    assert preview(user) == []


def test_turning_sending_off_takes_the_event_off_google(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, sync_to_google=True)
    ref = [{"source_type": "event", "source_id": made["id"]}]
    send(user, ref)
    user.patch(f"/calendar/events/{made['id']}", json={"sync_to_google": False})
    assert [c["action"] for c in preview(user)] == ["delete"]
    send(user, ref)
    assert calendar_api.events == {}
    assert len(events_on(user)) == 1  # still on the calendar page


# ------------------------------------------------------------------ failures, retry and duplicates


def test_a_failed_send_is_kept_with_its_reason_and_can_be_retried(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, sync_to_google=True)
    ref = [{"source_type": "event", "source_id": made["id"]}]
    assert state(user)["pending"] == 1

    calendar_api.fail["insert"] = 500
    failed = send(user, ref).json()
    assert failed["created"] == 0 and failed["failed"] == [
        {"source_type": "event", "source_id": made["id"], "error": "google_500"}
    ]
    after = state(user)
    assert (after["synced"], after["pending"], after["failed"]) == (0, 0, 1)
    (item,) = after["items"]
    assert item["state"] == "failed" and item["error"] == "google_500" and item["attempts"] == 1
    assert item["summary"] == "Dentist" and item["action"] == "create"
    assert events_on(user)[0]["sync"] == "failed"

    send(user, ref)  # fails again: counted
    assert state(user)["items"][0]["attempts"] == 2

    calendar_api.fail.clear()
    done = user.post(f"{BASE}/retry", json={}).json()
    assert done["created"] == 1 and done["failed"] == []
    assert state(user) == {"synced": 1, "pending": 0, "failed": 0, "items": []}
    assert len(calendar_api.events) == 1
    assert events_on(user)[0]["sync"] == "synced"


def test_retry_can_be_limited_to_chosen_items(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    first = add_event(user, "One", 3, sync_to_google=True)
    second = add_event(user, "Two", 4, sync_to_google=True)
    refs = [{"source_type": "event", "source_id": e["id"]} for e in (first, second)]
    calendar_api.fail["insert"] = 503
    assert len(send(user, refs).json()["failed"]) == 2
    calendar_api.fail.clear()
    assert user.post(f"{BASE}/retry", json={"items": [refs[0]]}).json()["created"] == 1
    assert [i["source_id"] for i in state(user)["items"]] == [second["id"]]
    assert [e["summary"] for e in calendar_api.events.values()] == ["One"]


def test_retry_drops_failures_for_things_that_no_longer_need_sending(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, sync_to_google=True)
    calendar_api.fail["insert"] = 500
    send(user, [{"source_type": "event", "source_id": made["id"]}])
    assert sql("SELECT count(*) FROM calendar_sync_failures WHERE source_id = :i", i=made["id"])[0][0] == 1
    user.delete(f"/calendar/events/{made['id']}")
    calendar_api.fail.clear()
    assert user.post(f"{BASE}/retry", json={}).json() == {"created": 0, "updated": 0, "deleted": 0, "failed": []}
    assert sql("SELECT count(*) FROM calendar_sync_failures WHERE source_id = :i", i=made["id"])[0][0] == 0
    assert calendar_api.events == {}


def test_sending_again_after_a_lost_answer_does_not_add_a_second_event(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    made = add_event(user, "Dentist", 3, start_time="16:00", sync_to_google=True)
    ref = [{"source_type": "event", "source_id": made["id"]}]
    send(user, ref)
    # Google made the event, but MindNest never heard back, so it believes nothing was sent.
    sql("DELETE FROM calendar_sync_items WHERE source_id = :i", i=made["id"])
    assert [c["action"] for c in preview(user)] == ["create"]
    assert send(user, ref).json()["created"] == 1
    assert len(calendar_api.events) == 1
    assert any(call[0] == "insert_duplicate" for call in calendar_api.calls)
    assert state(user)["synced"] == 1


def test_state_needs_a_connection(make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    response = user.get(f"{BASE}/state")
    assert response.status_code == 409 and response.json()["code"] == "gcal_not_connected"
    assert user.post(f"{BASE}/retry", json={}).status_code == 409


def test_exams_show_whether_they_are_on_google(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    exam_id = add_exam(user, 5, "Midterm")
    exam = next(e for e in user.get("/calendar", params={"from": day(0), "to": day(10)}).json()["events"] if e["kind"] == "exam")
    assert exam["sync"] is None  # Google is not connected
    connect(client, user, google)
    send(user, [{"source_type": "exam", "source_id": exam_id}])
    exam = next(e for e in user.get("/calendar", params={"from": day(0), "to": day(10)}).json()["events"] if e["kind"] == "exam")
    assert exam["sync"] == "synced"
