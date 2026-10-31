"""The calendar MCP server: the one place MindNest talks to Google Calendar.

Why a separate server: the chat agents (and the Calendar page) never see a Google token. They ask
this server, over the Model Context Protocol, to do one thing, and prove the student wants it with
a short-lived token made for exactly that call (see mindnest_core.mcptoken). The server then reads
the student's saved Google permission from the database (row-level security limited to that
student), gets a fresh access token from Google, and makes the Google Calendar call itself.

Google's permission is `calendar.app.created`: MindNest's own calendar named "MindNest AI", and
nothing else in the student's Google Calendar.

Every tool answers with a JSON object: {"ok": true, ...} or {"ok": false, "error": "<code>"}.
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mindnest_core.calevent import EventIn, Op, google_body, read_event
from mindnest_core.calsync import CALENDAR_NAME, MAX_SYNC_ITEMS
from mindnest_core.db import user_session
from mindnest_core.googlecalendar import CalendarApi, CalendarApiError
from mindnest_core.googleoauth import GoogleClient, GoogleError
from mindnest_core.mcptoken import ReplayGuard, TokenError, check_call, verify
from mindnest_core.settings import Settings
from mindnest_core.vault import VaultError, decrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("mindnest.calendar_mcp")

type SessionFactory = async_sessionmaker[AsyncSession]
CONCURRENCY = 4
MAX_RANGE_DAYS = 93


class Problem(Exception):
    """Something the caller should hear about, as a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def event_id_for(user_id: str, request_key: str) -> str:
    """The Google event id for a request. Google accepts our own ids made of the characters
    0-9 and a-v; a SHA-1 in hex fits. The same request therefore always names the same event, so
    asking twice never adds two."""
    return hashlib.sha1(f"{user_id}:{request_key}".encode()).hexdigest()  # noqa: S324 (an id, not security)


class CalendarService:
    """The tools' logic. Kept apart from the MCP wiring so it can be tested directly."""

    def __init__(
        self, settings: Settings, factory: SessionFactory, google: GoogleClient, calendar: CalendarApi,
        replay: ReplayGuard | None = None,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.google = google
        self.calendar = calendar
        self.replay = replay or ReplayGuard()

    # --- who is asking ------------------------------------------------------------------------
    def authorize(self, authorization: str | None, tool: str, args: dict[str, Any]) -> UUID:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer":
            raise Problem("forbidden")
        try:
            claims = verify(self.settings.secret_key, token.strip())
            check_call(claims, tool, args)
            self.replay.use(claims)
            return UUID(claims.user_id)
        except (TokenError, ValueError) as exc:
            log.warning("calendar call refused: %s", getattr(exc, "code", "bad_user"))
            raise Problem("forbidden") from exc

    # --- the student's saved Google permission -----------------------------------------------
    async def _link(self, user_id: UUID) -> dict[str, Any]:
        async with user_session(self.factory, user_id) as session:
            row = (
                await session.execute(
                    text("SELECT refresh_token_enc, calendar_id, needs_reconnect FROM google_calendar_links")
                )
            ).mappings().first()
        if row is None:
            raise Problem("gcal_not_connected")
        if row["needs_reconnect"]:
            raise Problem("gcal_reconnect")
        return dict(row)

    async def _needs_reconnect(self, user_id: UUID) -> None:
        async with user_session(self.factory, user_id) as session:
            await session.execute(text("UPDATE google_calendar_links SET needs_reconnect = true"))

    async def _access_token(self, user_id: UUID, link: dict[str, Any]) -> str:
        try:
            refresh = decrypt(self.settings.secret_key, link["refresh_token_enc"])
        except VaultError:
            await self._needs_reconnect(user_id)
            raise Problem("gcal_reconnect") from None
        try:
            access = str((await self.google.refresh(refresh)).get("access_token") or "")
        except GoogleError as exc:
            if exc.permanent:  # Google itself refused: the student has to connect again
                await self._needs_reconnect(user_id)
                raise Problem("gcal_reconnect") from None
            raise Problem("google_unavailable") from None
        if not access:
            raise Problem("google_unavailable")
        return access

    async def _session(self, user_id: UUID, need_calendar: bool = True) -> tuple[str, str]:
        link = await self._link(user_id)
        calendar_id = str(link["calendar_id"] or "")
        if need_calendar and not calendar_id:
            raise Problem("gcal_not_connected")
        return await self._access_token(user_id, link), calendar_id

    async def _google(self, user_id: UUID, call: Callable[[], Awaitable[Any]]) -> Any:
        """Run one Google call, turning its failures into codes."""
        try:
            return await call()
        except CalendarApiError as exc:
            if exc.unauthorized:
                await self._needs_reconnect(user_id)
                raise Problem("gcal_reconnect") from None
            if exc.rate_limited:
                raise Problem("rate_limited") from None
            if exc.missing:
                raise Problem("not_found") from None
            if exc.status == 0:
                raise Problem("google_unavailable") from None
            raise Problem(f"google_{exc.status}") from None

    # --- tools --------------------------------------------------------------------------------
    async def status(self, user_id: UUID) -> dict[str, Any]:
        async with user_session(self.factory, user_id) as session:
            row = (
                await session.execute(text("SELECT calendar_id, needs_reconnect FROM google_calendar_links"))
            ).mappings().first()
        if row is None:
            return {"ok": True, "connected": False, "needs_reconnect": False, "has_calendar": False}
        return {"ok": True, "connected": True, "needs_reconnect": bool(row["needs_reconnect"]),
                "has_calendar": bool(row["calendar_id"])}

    async def ensure_calendar(self, user_id: UUID) -> dict[str, Any]:
        """Make MindNest's own calendar in the student's Google Calendar, once."""
        link = await self._link(user_id)
        if link["calendar_id"]:
            return {"ok": True, "calendar_id": link["calendar_id"], "created": False}
        access = await self._access_token(user_id, link)
        calendar_id = await self._google(user_id, lambda: self.calendar.create_calendar(access, CALENDAR_NAME))
        async with user_session(self.factory, user_id) as session:
            await session.execute(
                text("UPDATE google_calendar_links SET calendar_id = :c"), {"c": calendar_id}
            )
        return {"ok": True, "calendar_id": calendar_id, "created": True}

    async def list_events(self, user_id: UUID, start: str, end: str, timezone: str, limit: int) -> dict[str, Any]:
        try:
            first, last, zone = date.fromisoformat(start), date.fromisoformat(end), ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise Problem("invalid_request") from None
        if last < first or (last - first).days > MAX_RANGE_DAYS:
            raise Problem("invalid_request")
        access, calendar_id = await self._session(user_id)
        time_min = datetime.combine(first, time.min, tzinfo=zone).isoformat()
        time_max = datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone).isoformat()
        raw = await self._google(
            user_id, lambda: self.calendar.list_events(access, calendar_id, time_min, time_max, limit)
        )
        events = [read_event(e) for e in raw if e.get("status") != "cancelled"]
        return {"ok": True, "events": events}

    async def get_event(self, user_id: UUID, event_id: str) -> dict[str, Any]:
        access, calendar_id = await self._session(user_id)
        raw = await self._google(user_id, lambda: self.calendar.get_event(access, calendar_id, event_id))
        if raw.get("status") == "cancelled":
            raise Problem("not_found")
        return {"ok": True, "event": read_event(raw)}

    async def create_event(self, user_id: UUID, request_key: str, event: EventIn) -> dict[str, Any]:
        access, calendar_id = await self._session(user_id)
        return await self._create(user_id, access, calendar_id, request_key, event)

    async def _create(
        self, user_id: UUID, access: str, calendar_id: str, request_key: str, event: EventIn
    ) -> dict[str, Any]:
        body = google_body(event)
        if request_key:
            body["id"] = event_id_for(str(user_id), request_key)
        try:
            raw = await self.calendar.create_event(access, calendar_id, body)
            return {"ok": True, "event": read_event(raw), "already_existed": False}
        except CalendarApiError as exc:
            if not (exc.duplicate and request_key):
                return await self._fail(user_id, exc)
        # The same request was already made: return that event instead of adding a second one.
        existing = await self._google(
            user_id, lambda: self.calendar.get_event(access, calendar_id, body["id"])
        )
        if existing.get("status") != "cancelled":
            return {"ok": True, "event": read_event(existing), "already_existed": True}
        # The student deleted it in Google since; Google keeps a deleted event's id, so add it
        # again without one.
        del body["id"]
        raw = await self._google(user_id, lambda: self.calendar.create_event(access, calendar_id, body))
        return {"ok": True, "event": read_event(raw), "already_existed": False}

    async def _fail(self, user_id: UUID, exc: CalendarApiError) -> dict[str, Any]:
        """Re-raise a Google failure as a Problem (it knows the codes)."""
        async def boom() -> None:
            raise exc

        await self._google(user_id, boom)
        raise AssertionError("unreachable")  # pragma: no cover

    async def update_event(self, user_id: UUID, event_id: str, event: EventIn) -> dict[str, Any]:
        access, calendar_id = await self._session(user_id)
        raw = await self._google(
            user_id, lambda: self.calendar.patch_event(access, calendar_id, event_id, google_body(event))
        )
        return {"ok": True, "event": read_event(raw) if raw else {"id": event_id}}

    async def delete_event(self, user_id: UUID, event_id: str) -> dict[str, Any]:
        access, calendar_id = await self._session(user_id)
        try:
            await self._google(user_id, lambda: self.calendar.delete_event(access, calendar_id, event_id))
        except Problem as problem:
            if problem.code != "not_found":
                raise
            return {"ok": True, "event_id": event_id, "already_gone": True}
        return {"ok": True, "event_id": event_id, "already_gone": False}

    async def apply_changes(self, user_id: UUID, ops: list[Op]) -> dict[str, Any]:
        """A batch of approved changes. One failure does not stop the others; a lost permission
        stops the whole batch (every call would fail the same way)."""
        if len(ops) > MAX_SYNC_ITEMS:
            raise Problem("invalid_request")
        access, calendar_id = await self._session(user_id)
        gate = asyncio.Semaphore(CONCURRENCY)
        results: list[dict[str, Any]] = [{} for _ in ops]

        async def one(index: int, op: Op) -> None:
            async with gate:
                try:
                    results[index] = {"index": index, **await self._apply(user_id, access, calendar_id, op)}
                except Problem as problem:
                    results[index] = {"index": index, "ok": False, "error": problem.code}

        await asyncio.gather(*(one(i, op) for i, op in enumerate(ops)))
        return {"ok": True, "results": results}

    async def _apply(self, user_id: UUID, access: str, calendar_id: str, op: Op) -> dict[str, Any]:
        if op.action == "delete":
            if not op.event_id:
                raise Problem("invalid_request")
            try:
                await self._google(user_id, lambda: self.calendar.delete_event(access, calendar_id, op.event_id))
            except Problem as problem:
                if problem.code != "not_found":  # already gone is fine
                    raise
            return {"ok": True, "event_id": None}
        if op.event is None:
            raise Problem("invalid_request")
        body = google_body(op.event)
        if op.action == "update" and op.event_id:
            try:
                await self._google(
                    user_id, lambda: self.calendar.patch_event(access, calendar_id, op.event_id, body)
                )
                return {"ok": True, "event_id": op.event_id}
            except Problem as problem:
                if problem.code != "not_found" or not op.recreate_missing:
                    raise
        if op.request_key:
            # Named by its key, so a retry after a timeout finds the event Google already made.
            done = await self._create(user_id, access, calendar_id, op.request_key, op.event)
            return {"ok": True, "event_id": str(done["event"]["id"])}
        raw = await self._google(user_id, lambda: self.calendar.create_event(access, calendar_id, body))
        return {"ok": True, "event_id": str(raw["id"])}

    async def remove_calendar(self, user_id: UUID) -> dict[str, Any]:
        """Delete MindNest's calendar (and so every event on it) from the student's Google Calendar."""
        link = await self._link(user_id)
        if not link["calendar_id"]:
            return {"ok": True, "removed": False}
        access = await self._access_token(user_id, link)
        try:
            await self._google(user_id, lambda: self.calendar.delete_calendar(access, str(link["calendar_id"])))
        except Problem as problem:
            if problem.code != "not_found":
                raise
        async with user_session(self.factory, user_id) as session:
            await session.execute(text("UPDATE google_calendar_links SET calendar_id = NULL"))
        return {"ok": True, "removed": True}


# --------------------------------------------------------------------------------------- MCP


def build_mcp(service: CalendarService) -> FastMCP:
    # This server is reached by the API over an internal network and every request must carry a
    # signed, single-use token, so browser-oriented host checking is switched off (it would only
    # reject the service's own hostname inside Docker).
    mcp = FastMCP(
        "MindNest Calendar",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def header(ctx: Context) -> str | None:  # type: ignore[type-arg]
        request = ctx.request_context.request
        return None if request is None else request.headers.get("authorization")

    async def run(
        ctx: Context, tool: str, args: dict[str, Any],  # type: ignore[type-arg]
        work: Callable[[UUID], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        try:
            user_id = service.authorize(header(ctx), tool, args)
            result = await work(user_id)
        except Problem as problem:
            return {"ok": False, "error": problem.code}
        except Exception:
            log.exception("calendar tool %s failed", tool)
            return {"ok": False, "error": "internal"}
        log.info("calendar tool %s ok", tool)
        return result

    @mcp.tool(description="Is Google Calendar connected for this student?")
    async def calendar_status(ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run(ctx, "calendar_status", {}, service.status)

    @mcp.tool(description="Create MindNest's own calendar in the student's Google Calendar if it does not exist yet.")
    async def ensure_calendar(ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run(ctx, "ensure_calendar", {}, service.ensure_calendar)

    @mcp.tool(description="List events on MindNest's calendar between two days (YYYY-MM-DD), in the student's time zone.")
    async def list_events(
        start: str, end: str, timezone: str, limit: int, ctx: Context  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        args = {"start": start, "end": end, "timezone": timezone, "limit": limit}
        return await run(ctx, "list_events", args, lambda u: service.list_events(u, start, end, timezone, limit))

    @mcp.tool(description="Read one event on MindNest's calendar.")
    async def get_event(event_id: str, ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run(ctx, "get_event", {"event_id": event_id}, lambda u: service.get_event(u, event_id))

    @mcp.tool(description="Add an event to MindNest's calendar. The same request_key never adds two events.")
    async def create_event(request_key: str, event: EventIn, ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        args = {"request_key": request_key, "event": event.model_dump(mode="json")}
        return await run(ctx, "create_event", args, lambda u: service.create_event(u, request_key, event))

    @mcp.tool(description="Change an event on MindNest's calendar.")
    async def update_event(event_id: str, event: EventIn, ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        args = {"event_id": event_id, "event": event.model_dump(mode="json")}
        return await run(ctx, "update_event", args, lambda u: service.update_event(u, event_id, event))

    @mcp.tool(description="Remove an event from MindNest's calendar.")
    async def delete_event(event_id: str, ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run(ctx, "delete_event", {"event_id": event_id}, lambda u: service.delete_event(u, event_id))

    @mcp.tool(description="Apply a batch of approved changes (create, update, delete) to MindNest's calendar.")
    async def apply_changes(ops: list[Op], ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        args = {"ops": [op.model_dump(mode="json") for op in ops]}
        return await run(ctx, "apply_changes", args, lambda u: service.apply_changes(u, ops))

    @mcp.tool(description="Delete MindNest's calendar from the student's Google Calendar, with all its events.")
    async def remove_calendar(ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run(ctx, "remove_calendar", {}, service.remove_calendar)

    return mcp


class GuardedApp:
    """The MCP app behind a gate: no request without a valid, unexpired token reaches it
    (`/health` excepted). Which tool and arguments a token is for is checked inside each tool."""

    def __init__(self, inner: ASGIApp, secret_key: str) -> None:
        self.inner = inner
        self.secret_key = secret_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        if scope["path"] == "/health":
            await PlainTextResponse("ok")(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        scheme, _, token = headers.get("authorization", "").partition(" ")
        try:
            if scheme.lower() != "bearer":
                raise TokenError("missing_token")
            verify(self.secret_key, token.strip())
        except TokenError as exc:
            response = JSONResponse({"error": exc.code}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        await self.inner(scope, receive, send)


def create_app(service: CalendarService) -> ASGIApp:
    return GuardedApp(build_mcp(service).streamable_http_app(), service.settings.secret_key)
