"""The Google Calendar client, against a fake HTTP server."""

import json

import httpx
import pytest
from mindnest_core.googlecalendar import API, SCOPE, CalendarApi, CalendarApiError


def make(handler):
    return CalendarApi(transport=httpx.MockTransport(handler))


async def test_it_asks_only_for_the_narrow_permission():
    assert SCOPE.endswith("calendar.app.created")
    assert "calendar.events" not in SCOPE and not SCOPE.endswith("/calendar")


async def test_create_calendar_returns_its_id_and_sends_the_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"id": "abc@group.calendar.google.com"})

    api = make(handler)
    assert await api.create_calendar("tok", "MindNest AI") == "abc@group.calendar.google.com"
    assert seen == {"url": f"{API}/calendars", "auth": "Bearer tok", "body": {"summary": "MindNest AI"}}
    await api.aclose()


async def test_ids_are_escaped_in_the_url():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.raw_path.decode()))
        return httpx.Response(200, json={"id": "e1"}) if request.method == "POST" else httpx.Response(204)

    api = make(handler)
    await api.insert_event("t", "a@group.calendar.google.com", {"summary": "x"})
    await api.patch_event("t", "a@b/../c", "e/1", {})
    await api.delete_event("t", "cal", "e1")
    await api.delete_calendar("t", "cal")
    assert seen[0] == ("POST", "/calendar/v3/calendars/a%40group.calendar.google.com/events")
    assert seen[1] == ("PATCH", "/calendar/v3/calendars/a%40b%2F..%2Fc/events/e%2F1")
    assert seen[2] == ("DELETE", "/calendar/v3/calendars/cal/events/e1")
    assert seen[3] == ("DELETE", "/calendar/v3/calendars/cal")


@pytest.mark.parametrize(
    ("status", "reason", "missing", "limited", "unauthorized"),
    [
        (404, "notFound", True, False, False),
        (410, "deleted", True, False, False),
        (429, "", False, True, False),
        (403, "rateLimitExceeded", False, True, False),
        (403, "userRateLimitExceeded", False, True, False),
        (401, "authError", False, False, True),
        (500, "", False, False, False),
    ],
)
async def test_errors_say_what_kind_of_failure_it_was(status, reason, missing, limited, unauthorized):
    body = {"error": {"errors": [{"reason": reason}]}} if reason else {}
    api = make(lambda request: httpx.Response(status, json=body))
    with pytest.raises(CalendarApiError) as caught:
        await api.delete_event("t", "c", "e")
    error = caught.value
    assert error.status == status and error.reason == reason
    assert (error.missing, error.rate_limited, error.unauthorized) == (missing, limited, unauthorized)


async def test_a_network_failure_is_an_error_not_a_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(CalendarApiError) as caught:
        await make(handler).create_calendar("t", "x")
    assert caught.value.status == 0


async def test_an_answer_without_an_id_is_rejected():
    api = make(lambda request: httpx.Response(200, json={}))
    with pytest.raises(CalendarApiError):
        await api.create_calendar("t", "x")
    with pytest.raises(CalendarApiError):
        await api.insert_event("t", "c", {})


async def test_an_unreadable_answer_is_rejected():
    api = make(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(CalendarApiError) as caught:
        await api.create_calendar("t", "x")
    assert caught.value.status == 502


async def test_create_event_sends_our_id_and_returns_the_link():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc123", "htmlLink": "https://calendar.google.com/e"})

    created = await make(handler).create_event("t", "cal", {"id": "abc123", "summary": "x"})
    assert seen["body"]["id"] == "abc123" and created["htmlLink"].startswith("https://calendar.google.com")


async def test_a_repeated_id_is_recognised_as_a_duplicate():
    api = make(lambda request: httpx.Response(409, json={"error": {"errors": [{"reason": "duplicate"}]}}))
    with pytest.raises(CalendarApiError) as caught:
        await api.create_event("t", "cal", {"id": "abc123"})
    assert caught.value.duplicate and not caught.value.missing


async def test_list_events_asks_for_a_window_in_start_order():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [{"id": "a"}, "junk", {"id": "b"}]})

    events = await make(handler).list_events("t", "cal", "2026-11-01T00:00:00+05:30", "2026-11-08T00:00:00+05:30", 500)
    assert [e["id"] for e in events] == ["a", "b"]
    assert seen["params"]["singleEvents"] == "true" and seen["params"]["orderBy"] == "startTime"
    assert seen["params"]["timeMin"].startswith("2026-11-01") and seen["params"]["maxResults"] == "250"


async def test_get_and_patch_return_the_event():
    api = make(lambda request: httpx.Response(200, json={"id": "e1", "summary": "x"}))
    assert (await api.get_event("t", "cal", "e1"))["id"] == "e1"
    assert (await api.patch_event("t", "cal", "e1", {"summary": "x"}))["summary"] == "x"
