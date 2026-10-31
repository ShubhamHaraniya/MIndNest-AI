"""The calendar MCP server, reached over real HTTP exactly as the API reaches it.

Only Google is replaced by fakes. Covers the doors (who may call), the tools (what they do) and
the failure words they answer with."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mindnest_api.calendar_gateway import CalendarGateway, CalendarToolError
from mindnest_api.vault import encrypt
from mindnest_core.calevent import EventIn
from mindnest_core.db import make_engine
from mindnest_core.googlecalendar import SCOPE
from mindnest_core.mcptoken import mint
from mindnest_core.settings import get_settings
from sqlalchemy import text

SETTINGS = get_settings()


def owner(query: str, **params: Any) -> list[Any]:
    async def go() -> list[Any]:
        engine = make_engine(SETTINGS.migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.mappings().all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def link_google(user: Any, calendar_id: str | None = "cal-test") -> None:
    owner(
        "INSERT INTO google_calendar_links (user_id, refresh_token_enc, scope, calendar_id) "
        "VALUES (:u, :t, :s, :c)",
        u=uuid.UUID(user.id), t=encrypt(SETTINGS.secret_key, "1//fake"), s=SCOPE, c=calendar_id,
    )


def gateway(url: str) -> CalendarGateway:
    return CalendarGateway(SETTINGS, url=url)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def error_of(coro: Any) -> str:
    with pytest.raises(CalendarToolError) as caught:
        asyncio.run(coro)
    return caught.value.code


def exam_day(offset: int = 5) -> date:
    return datetime.now(UTC).date() + timedelta(days=offset)


def study(summary: str = "Study: cells", **kw: Any) -> EventIn:
    return EventIn(summary=summary, day=exam_day(), start_time="18:30", minutes=45, timezone="Asia/Kolkata", **kw)


async def raw_call(url: str, token: str | None, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool with a hand-made token, the way an attacker (or a bug) might."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=15) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
    assert result.structuredContent is not None
    return dict(result.structuredContent)


# ------------------------------------------------------------------ the door


def test_health_needs_no_token_but_nothing_else_works_without_one(calendar_server_url):  # type: ignore[no-untyped-def]
    base = calendar_server_url.removesuffix("/mcp")
    assert httpx.get(f"{base}/health").text == "ok"
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
        response = httpx.post(calendar_server_url, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert response.status_code == 401, headers


def test_a_token_signed_with_another_key_or_expired_is_refused(calendar_server_url):  # type: ignore[no-untyped-def]
    for token in (
        mint("x" * 40, str(uuid.uuid4()), "calendar_status", {}),
        mint(SETTINGS.secret_key, str(uuid.uuid4()), "calendar_status", {}, now=1.0),
    ):
        response = httpx.post(
            calendar_server_url, headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert response.status_code == 401


def test_a_token_for_another_tool_or_other_arguments_does_nothing(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    status_token = mint(SETTINGS.secret_key, user.id, "calendar_status", {})
    assert run(raw_call(calendar_server_url, status_token, "remove_calendar", {})) == {"ok": False, "error": "forbidden"}
    event = {"event_id": "abc"}
    token = mint(SETTINGS.secret_key, user.id, "delete_event", event)
    assert run(raw_call(calendar_server_url, token, "delete_event", {"event_id": "other"}))["error"] == "forbidden"
    assert calendar_api.calls == []


def test_a_token_works_only_once(make_user, calendar_server_url):  # type: ignore[no-untyped-def]
    user = make_user()
    token = mint(SETTINGS.secret_key, user.id, "calendar_status", {})
    assert run(raw_call(calendar_server_url, token, "calendar_status", {}))["ok"] is True
    assert run(raw_call(calendar_server_url, token, "calendar_status", {})) == {"ok": False, "error": "forbidden"}


def test_a_token_that_names_no_real_student_is_refused(calendar_server_url):  # type: ignore[no-untyped-def]
    token = mint(SETTINGS.secret_key, "not-a-uuid", "calendar_status", {})
    assert run(raw_call(calendar_server_url, token, "calendar_status", {}))["error"] == "forbidden"


# ------------------------------------------------------------------ the tools


def test_status_before_and_after_connecting(make_user, calendar_server_url):  # type: ignore[no-untyped-def]
    user = make_user()
    gw = gateway(calendar_server_url)
    assert run(gw.status(user.id)) == {"ok": True, "connected": False, "needs_reconnect": False, "has_calendar": False}
    link_google(user, calendar_id=None)
    assert run(gw.status(user.id))["has_calendar"] is False
    assert error_of(gw.list_events(user.id, "2026-11-01", "2026-11-07", "UTC")) == "gcal_not_connected"


def test_ensure_calendar_makes_mindnest_ai_once(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user, calendar_id=None)
    gw = gateway(calendar_server_url)
    first = run(gw.ensure_calendar(user.id))
    again = run(gw.ensure_calendar(user.id))
    assert first["created"] is True and again["created"] is False and first["calendar_id"] == again["calendar_id"]
    assert calendar_api.calendars == ["MindNest AI"]
    assert owner("SELECT calendar_id FROM google_calendar_links WHERE user_id = :u", u=uuid.UUID(user.id))[0]["calendar_id"]


def test_a_student_who_never_connected_gets_a_clear_answer(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    gw = gateway(calendar_server_url)
    assert error_of(gw.create_event(user.id, "k1", study())) == "gcal_not_connected"
    assert error_of(gw.ensure_calendar(user.id)) == "gcal_not_connected"
    assert calendar_api.calls == []


def test_create_list_get_update_delete_on_the_students_own_calendar(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user, "cal-mine")
    gw = gateway(calendar_server_url)
    made = run(gw.create_event(user.id, "run1:t1", study()))
    assert made["link"].startswith("https://calendar.google.com/") and made["start_time"] == "18:30" and made["minutes"] == 45
    assert calendar_api.calendar_of[made["id"]] == "cal-mine"

    listed = run(gw.list_events(user.id, exam_day(0).isoformat(), exam_day(10).isoformat(), "Asia/Kolkata"))
    assert [e["id"] for e in listed] == [made["id"]]
    assert run(gw.get_event(user.id, made["id"]))["summary"] == "Study: cells"

    moved = run(gw.update_event(user.id, made["id"], study("Study: cells (moved)")))
    assert moved["summary"] == "Study: cells (moved)" and moved["id"] == made["id"]

    run(gw.delete_event(user.id, made["id"]))
    assert calendar_api.events == {}
    run(gw.delete_event(user.id, made["id"]))  # already gone is fine
    assert error_of(gw.get_event(user.id, made["id"])) == "not_found"


def test_asking_twice_for_the_same_thing_adds_one_event(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    gw = gateway(calendar_server_url)
    a = run(gw.create_event(user.id, "run9:call1", study()))
    b = run(gw.create_event(user.id, "run9:call1", study()))
    assert a["id"] == b["id"] and len(calendar_api.events) == 1
    c = run(gw.create_event(user.id, "run9:call2", study()))
    assert c["id"] != a["id"] and len(calendar_api.events) == 2


def test_a_batch_create_with_a_request_key_never_adds_two_events(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    from mindnest_core.calevent import Op

    user = make_user()
    link_google(user)
    gw = gateway(calendar_server_url)
    keyed = Op(action="create", event=study(), request_key="gcal:task:1:abc")
    first = run(gw.apply_changes(user.id, [keyed]))
    second = run(gw.apply_changes(user.id, [keyed]))
    assert first[0]["ok"] and second[0]["ok"] and first[0]["event_id"] == second[0]["event_id"]
    assert len(calendar_api.events) == 1
    # Without a key the old behaviour stands: every create is a new event.
    plain = Op(action="create", event=study())
    run(gw.apply_changes(user.id, [plain, plain]))
    assert len(calendar_api.events) == 3


def test_the_same_request_key_from_two_students_makes_two_events(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    a, b = make_user(), make_user()
    link_google(a, "cal-a")
    link_google(b, "cal-b")
    gw = gateway(calendar_server_url)
    ea = run(gw.create_event(a.id, "same", study()))
    eb = run(gw.create_event(b.id, "same", study()))
    assert ea["id"] != eb["id"]
    assert (calendar_api.calendar_of[ea["id"]], calendar_api.calendar_of[eb["id"]]) == ("cal-a", "cal-b")


def test_an_event_the_student_deleted_in_google_can_be_added_again(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    gw = gateway(calendar_server_url)
    first = run(gw.create_event(user.id, "k", study()))
    calendar_api.events.pop(first["id"])
    calendar_api.deleted_ids.add(first["id"])  # Google keeps the id of a deleted event
    again = run(gw.create_event(user.id, "k", study()))
    assert again["id"] != first["id"] and again["id"] in calendar_api.events


def test_a_long_range_is_refused(make_user, calendar_server_url):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    gw = gateway(calendar_server_url)
    assert error_of(gw.list_events(user.id, "2026-01-01", "2027-12-31", "UTC")) == "invalid_request"
    assert error_of(gw.list_events(user.id, "2026-01-10", "2026-01-01", "UTC")) == "invalid_request"
    assert error_of(gw.list_events(user.id, "2026-01-01", "2026-01-05", "Mars/Base")) == "invalid_request"


# ------------------------------------------------------------------ when Google says no


def test_a_refused_refresh_token_means_connect_again_and_is_remembered(make_user, calendar_server_url, calendar_api, google):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    gw = gateway(calendar_server_url)
    google.refresh_fail = True
    assert error_of(gw.create_event(user.id, "k", study())) == "gcal_reconnect"
    google.refresh_fail = False
    assert error_of(gw.create_event(user.id, "k", study())) == "gcal_reconnect"  # until they reconnect
    assert run(gw.status(user.id))["needs_reconnect"] is True
    assert calendar_api.events == {}


def test_google_rejecting_the_access_token_means_connect_again(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    calendar_api.fail["insert"] = 401
    assert error_of(gateway(calendar_server_url).create_event(user.id, "k", study())) == "gcal_reconnect"


@pytest.mark.parametrize(("status", "code"), [(429, "rate_limited"), (403, "google_403"), (500, "google_500"), (0, "google_unavailable")])
def test_other_google_failures_have_stable_words(make_user, calendar_server_url, calendar_api, status, code):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user)
    calendar_api.fail["insert"] = status
    assert error_of(gateway(calendar_server_url).create_event(user.id, "k", study())) == code


def test_a_server_that_is_down_is_reported_as_unavailable(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert error_of(gateway("http://127.0.0.1:9/mcp").status(user.id)) == "calendar_unavailable"


def test_removing_the_calendar_forgets_its_id(make_user, calendar_server_url, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    link_google(user, "cal-gone")
    gw = gateway(calendar_server_url)
    run(gw.remove_calendar(user.id))
    assert calendar_api.deleted_calendars == ["cal-gone"]
    assert run(gw.status(user.id))["has_calendar"] is False
