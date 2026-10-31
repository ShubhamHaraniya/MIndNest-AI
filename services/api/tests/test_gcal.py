"""Putting study dates on Google Calendar, with Google replaced by fakes."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from mindnest_api.routes.gcal import FLOW_COOKIE
from mindnest_api.vault import decrypt
from mindnest_core.calsync import CALENDAR_NAME
from mindnest_core.db import make_engine
from mindnest_core.googlecalendar import SCOPE
from mindnest_core.settings import get_settings
from sqlalchemy import text

BASE = "/integrations/google-calendar"
SESSION = get_settings().session_cookie_name


def sql(query: str, **params: Any) -> list[Any]:
    async def go() -> list[Any]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def callback(client, user, flow_cookie, *, state, code="one-time-code", **query):  # type: ignore[no-untyped-def]
    cookies = [f"{FLOW_COOKIE}={flow_cookie}"] if flow_cookie else []
    if user is not None and user.token:
        cookies.append(f"{SESSION}={user.token}")
    params = {"code": code, "state": state, **query}
    params = {k: v for k, v in params.items() if v}
    client.cookies.clear()
    response = client.get(
        f"/api/v1{BASE}/callback", params=params, headers={"cookie": "; ".join(cookies)}, follow_redirects=False
    )
    client.cookies.clear()
    return response


def begin(client, user):  # type: ignore[no-untyped-def]
    """The student presses Connect. Returns (state, cookie value, redirect response)."""
    client.cookies.clear()
    response = client.get(
        f"/api/v1{BASE}/start", headers={"cookie": f"{SESSION}={user.token}"}, follow_redirects=False
    )
    client.cookies.clear()
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], response.cookies.get(FLOW_COOKIE), response


def connect(client, user, google):  # type: ignore[no-untyped-def]
    google.scope = f"openid {SCOPE}"
    state, cookie, _ = begin(client, user)
    response = callback(client, user, cookie, state=state)
    assert response.headers["location"].endswith("/calendar?gcal=connected"), response.headers["location"]


def outcome(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.headers["location"]).rsplit("gcal=", 1)[-1]


def add_exam(user, offset=10, title="Midterm"):  # type: ignore[no-untyped-def]
    response = user.post("/exams", json={"title": title, "exam_on": day(offset)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_assignment(user, offset=6, title="Osmosis essay"):  # type: ignore[no-untyped-def]
    due = (datetime.now(UTC) + timedelta(days=offset)).replace(hour=12, minute=0, second=0, microsecond=0)
    response = user.post("/assignments", json={"title": title, "brief": "Explain osmosis.", "due_at": due.isoformat()})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_task(user, offset=2, title="Revise cells", minutes=45):  # type: ignore[no-untyped-def]
    response = user.post("/planner/tasks", json={"title": title, "planned_for": day(offset), "minutes": minutes})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def everything(changes):  # type: ignore[no-untyped-def]
    return [{"source_type": c["source_type"], "source_id": c["source_id"]} for c in changes]


def preview(user):  # type: ignore[no-untyped-def]
    response = user.get(f"{BASE}/preview")
    assert response.status_code == 200, response.text
    return response.json()["changes"]


def send(user, items):  # type: ignore[no-untyped-def]
    return user.post(f"{BASE}/sync", json={"items": items})


# ------------------------------------------------------------------ connecting


def test_status_says_whether_google_is_set_up_and_whether_the_student_is_connected(make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get(BASE).json() == {
        "available": True, "connected": False, "needs_reconnect": False,
        "connected_at": None, "last_synced_at": None, "synced_items": 0,
    }


def test_nothing_works_until_google_is_configured(make_user, client):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get(BASE).json()["available"] is False
    response = client.get(f"/api/v1{BASE}/start", headers={"cookie": f"{SESSION}={user.token}"}, follow_redirects=False)
    client.cookies.clear()
    assert response.status_code == 503 and response.json()["code"] == "google_not_configured"


def test_connecting_needs_a_signed_in_student(client, google):  # type: ignore[no-untyped-def]
    client.cookies.clear()
    assert client.get(f"/api/v1{BASE}/start", follow_redirects=False).status_code == 401


def test_start_asks_google_for_the_narrow_calendar_permission_and_a_refresh_token(client, make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    state, cookie, response = begin(client, user)
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["scope"] == [SCOPE]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["redirect_uri"][0].endswith("/api/v1/integrations/google-calendar/callback")
    assert query["code_challenge_method"] == ["S256"]
    header = response.headers["set-cookie"].lower()
    assert FLOW_COOKIE in header and "httponly" in header and "samesite=lax" in header
    assert state and cookie


def test_a_successful_connection_makes_the_calendar_and_stores_the_token_encrypted(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    assert ("create_calendar", CALENDAR_NAME) in calendar_api.calls
    (row,) = sql("SELECT refresh_token_enc, scope, calendar_id, needs_reconnect FROM google_calendar_links WHERE user_id = :u", u=user.id)
    assert row.refresh_token_enc != "1//fake" and "1//fake" not in row.refresh_token_enc
    assert decrypt(get_settings().secret_key, row.refresh_token_enc) == "1//fake"
    assert row.scope == SCOPE and row.calendar_id.startswith("cal-") and row.needs_reconnect is False
    status = user.get(BASE).json()
    assert status["connected"] is True and status["needs_reconnect"] is False


def test_the_callback_refuses_a_wrong_state_or_missing_cookie(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    google.scope = SCOPE
    state, cookie, _ = begin(client, user)
    assert outcome(callback(client, user, cookie, state="not-the-state")) == "error_failed"
    assert outcome(callback(client, user, None, state=state)) == "error_failed"
    assert outcome(callback(client, user, "garbage", state=state)) == "error_failed"
    assert user.get(BASE).json()["connected"] is False
    assert calendar_api.calendars == []


def test_a_different_signed_in_student_cannot_finish_someone_elses_connection(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    google.scope = SCOPE
    state, cookie, _ = begin(client, alice)
    assert outcome(callback(client, bob, cookie, state=state)) == "error_failed"
    assert outcome(callback(client, None, cookie, state=state)) == "error_signin"
    assert alice.get(BASE).json()["connected"] is False and bob.get(BASE).json()["connected"] is False


def test_the_student_can_say_no_at_googles_consent_screen(client, make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    state, cookie, _ = begin(client, user)
    response = callback(client, user, cookie, state=state, code="", error="access_denied")
    assert outcome(response) == "cancelled"
    assert user.get(BASE).json()["connected"] is False


def test_it_refuses_a_connection_without_a_refresh_token_or_the_calendar_permission(client, make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    google.scope, google.refresh_token = SCOPE, None
    state, cookie, _ = begin(client, user)
    assert outcome(callback(client, user, cookie, state=state)) == "error_no_refresh"
    google.refresh_token, google.scope = "1//fake", "openid email"
    state, cookie, _ = begin(client, user)
    assert outcome(callback(client, user, cookie, state=state)) == "error_scope"
    assert user.get(BASE).json()["connected"] is False


def test_a_google_failure_while_connecting_is_reported_not_raised(client, make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    google.scope, google.fail = SCOPE, True
    state, cookie, _ = begin(client, user)
    assert outcome(callback(client, user, cookie, state=state)) == "error_failed"


def test_connecting_again_replaces_the_token_and_forgets_the_old_calendars_events(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user)
    assert send(user, everything(preview(user))).status_code == 200
    assert user.get(BASE).json()["synced_items"] == 1
    sql("UPDATE google_calendar_links SET needs_reconnect = true WHERE user_id = :u", u=user.id)
    connect(client, user, google)
    status = user.get(BASE).json()
    assert status["needs_reconnect"] is False and status["synced_items"] == 0
    assert len(preview(user)) == 1  # it would be sent afresh to the new calendar


# ------------------------------------------------------------------ what would be sent


def test_the_preview_lists_exams_due_assignments_and_planned_tasks_in_date_order(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10, "Midterm")
    add_assignment(user, 6, "Osmosis essay")
    add_task(user, 2, "Revise cells", 45)
    changes = preview(user)
    assert [(c["action"], c["source_type"]) for c in changes] == [
        ("create", "task"), ("create", "assignment"), ("create", "exam"),
    ]
    assert changes[0]["summary"] == "Study: Revise cells (45 min)"
    assert changes[1]["summary"] == "Due: Osmosis essay"
    assert changes[2]["summary"] == "Exam: Midterm"
    assert [c["day"] for c in changes] == sorted(c["day"] for c in changes)


def test_finished_and_past_items_are_not_offered(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 0, "Today")  # still counts
    sql("INSERT INTO exams (user_id, title, exam_on) VALUES (:u, 'Old', CURRENT_DATE - 3)", u=user.id)
    done = add_task(user, 1, "Finished")
    assert user.patch(f"/planner/tasks/{done}", json={"status": "done"}).status_code == 200
    assert [c["summary"] for c in preview(user)] == ["Exam: Today"]


def test_the_preview_follows_the_students_language(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    assert user.patch("/me", json={"ui_language": "hi"}).status_code == 200
    add_exam(user, 5, "Biology")
    assert preview(user)[0]["summary"] == "परीक्षा: Biology"


def test_preview_and_sync_need_a_connection_first(make_user, google):  # type: ignore[no-untyped-def]
    user = make_user()
    for response in (user.get(f"{BASE}/preview"), send(user, [{"source_type": "exam", "source_id": "00000000-0000-0000-0000-000000000001"}])):
        assert response.status_code == 409 and response.json()["code"] == "gcal_not_connected"


# ------------------------------------------------------------------ sending


def test_approved_items_become_all_day_events_with_the_right_text(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10, "Midterm")
    add_task(user, 2, "Revise cells", 45)
    response = send(user, everything(preview(user)))
    assert response.status_code == 200, response.text
    assert response.json() == {"created": 2, "updated": 0, "deleted": 0, "failed": []}
    bodies = {b["summary"]: b for b in calendar_api.events.values()}
    exam = bodies["Exam: Midterm"]
    assert exam["start"] == {"date": day(10)} and exam["end"] == {"date": day(11)}
    assert exam["transparency"] == "transparent"
    assert exam["extendedProperties"]["private"]["source"] == "exam"
    assert "/planner" in exam["description"]
    assert user.get(BASE).json()["synced_items"] == 2 and user.get(BASE).json()["last_synced_at"]
    assert preview(user) == []  # nothing left to send


def test_only_the_ticked_items_are_sent(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10, "Midterm")
    add_task(user, 2, "Revise cells")
    only_task = [c for c in preview(user) if c["source_type"] == "task"]
    assert send(user, everything(only_task)).json()["created"] == 1
    assert [e["summary"] for e in calendar_api.events.values()] == ["Study: Revise cells (45 min)"]
    assert [c["source_type"] for c in preview(user)] == ["exam"]


def test_the_browser_cannot_send_things_the_server_did_not_propose(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    other = make_user("Other")
    stranger = add_exam(other, 5, "Not yours")
    response = send(user, [
        {"source_type": "exam", "source_id": stranger},
        {"source_type": "exam", "source_id": "00000000-0000-0000-0000-000000000002"},
    ])
    assert response.status_code == 200 and response.json()["created"] == 0
    assert calendar_api.events == {}
    assert send(user, [{"source_type": "calendar", "source_id": stranger}]).status_code == 422
    assert user.post(f"{BASE}/sync", json={"items": []}).status_code == 422


def test_an_edited_item_updates_the_same_event(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    exam = add_exam(user, 10, "Midterm")
    send(user, everything(preview(user)))
    (event_id,) = calendar_api.events
    assert user.patch(f"/exams/{exam}", json={"title": "Final", "exam_on": day(12)}).status_code == 200
    changes = preview(user)
    assert [(c["action"], c["summary"]) for c in changes] == [("update", "Exam: Final")]
    assert send(user, everything(changes)).json() == {"created": 0, "updated": 1, "deleted": 0, "failed": []}
    assert list(calendar_api.events) == [event_id]
    assert calendar_api.events[event_id]["start"] == {"date": day(12)}
    assert preview(user) == []


def test_a_removed_or_finished_item_deletes_its_event(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    exam = add_exam(user, 10)
    task = add_task(user, 2)
    send(user, everything(preview(user)))
    assert len(calendar_api.events) == 2
    assert user.delete(f"/exams/{exam}").status_code == 204
    assert user.patch(f"/planner/tasks/{task}", json={"status": "done"}).status_code == 200
    changes = preview(user)
    assert sorted(c["action"] for c in changes) == ["delete", "delete"]
    assert send(user, everything(changes)).json()["deleted"] == 2
    assert calendar_api.events == {}
    assert user.get(BASE).json()["synced_items"] == 0


def test_an_event_the_student_deleted_in_google_is_put_back_on_update_and_forgiven_on_delete(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    exam, task = add_exam(user, 10), add_task(user, 2)
    send(user, everything(preview(user)))
    calendar_api.events.clear()  # the student removed both events inside Google Calendar
    assert user.patch(f"/exams/{exam}", json={"title": "Final"}).status_code == 200
    assert user.delete(f"/planner/tasks/{task}").status_code == 204
    result = send(user, everything(preview(user))).json()
    assert result == {"created": 0, "updated": 1, "deleted": 1, "failed": []}
    assert [e["summary"] for e in calendar_api.events.values()] == ["Exam: Final"]


def test_one_failure_does_not_stop_the_others(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10)
    calendar_api.fail["insert"] = 500
    result = send(user, everything(preview(user))).json()
    assert result["created"] == 0 and result["failed"][0]["error"] == "google_500"
    calendar_api.fail["insert"] = 429
    assert send(user, everything(preview(user))).json()["failed"][0]["error"] == "rate_limited"
    calendar_api.fail.clear()
    assert send(user, everything(preview(user))).json()["created"] == 1  # a failed item is simply offered again


def test_a_refused_refresh_token_asks_the_student_to_reconnect(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10)
    changes = preview(user)
    google.refresh_fail = True
    response = send(user, everything(changes))
    assert response.status_code == 409 and response.json()["code"] == "gcal_reconnect"
    assert user.get(BASE).json()["needs_reconnect"] is True
    assert user.get(f"{BASE}/preview").json()["code"] == "gcal_reconnect"
    assert calendar_api.events == {}


def test_google_rejecting_the_access_token_also_asks_to_reconnect(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    add_exam(user, 10)
    calendar_api.fail["insert"] = 401
    response = send(user, everything(preview(user)))
    assert response.status_code == 409 and response.json()["code"] == "gcal_reconnect"
    assert user.get(BASE).json()["needs_reconnect"] is True


# ------------------------------------------------------------------ disconnecting, privacy


def test_disconnecting_can_keep_or_remove_the_calendar(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    keeper, remover = make_user("Keeper"), make_user("Remover")
    for user in (keeper, remover):
        connect(client, user, google)
        add_exam(user, 10)
        send(user, everything(preview(user)))
    assert keeper.delete(BASE).status_code == 204
    assert calendar_api.deleted_calendars == [] and google.revoked == ["1//fake"]
    assert remover.delete(f"{BASE}?remove_events=true").status_code == 204
    assert len(calendar_api.deleted_calendars) == 1
    for user in (keeper, remover):
        assert user.get(BASE).json()["connected"] is False
        assert sql("SELECT count(*) FROM calendar_sync_items WHERE user_id = :u", u=user.id)[0][0] == 0
        assert sql("SELECT count(*) FROM google_calendar_links WHERE user_id = :u", u=user.id)[0][0] == 0


def test_disconnecting_when_not_connected_is_harmless(make_user, google):  # type: ignore[no-untyped-def]
    assert make_user().delete(BASE).status_code == 204


def test_disconnecting_works_even_if_google_is_unreachable(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    google.refresh_fail = True
    assert user.delete(f"{BASE}?remove_events=true").status_code == 204
    assert user.get(BASE).json()["connected"] is False


def test_each_student_only_sees_their_own_connection_and_changes(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    connect(client, alice, google)
    add_exam(alice, 10)
    assert bob.get(BASE).json()["connected"] is False
    assert bob.get(f"{BASE}/preview").status_code == 409
    assert len(preview(alice)) == 1


def test_deleting_the_account_data_removes_the_link(client, make_user, google, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    connect(client, user, google)
    sql("DELETE FROM users WHERE id = :u", u=user.id)
    assert sql("SELECT count(*) FROM google_calendar_links WHERE user_id = :u", u=user.id)[0][0] == 0
