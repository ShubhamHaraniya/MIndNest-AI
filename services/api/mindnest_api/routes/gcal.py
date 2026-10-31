"""Putting exams, assignment deadlines and study tasks on the student's Google Calendar.

Connecting is a separate Google consent from signing in, and asks only for permission to make
and manage MindNest's own calendar. Nothing is sent until the student has seen the list of
changes and approved it; the API rebuilds every event from the database, so the browser can
only choose among changes the server itself proposed.
"""

import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from mindnest_core.calevent import Op
from mindnest_core.calsync import (
    MAX_SYNC_ITEMS,
    Candidate,
    Change,
    Synced,
    diff,
    event_in,
    summary_for,
)
from mindnest_core.db import user_session
from mindnest_core.googlecalendar import SCOPE
from mindnest_core.googleoauth import GoogleError, authorize_url, pkce_pair, seal, unseal
from mindnest_core.plannerlogic import local_today, local_zone
from mindnest_core.settings import (
    get_settings,
    google_calendar_redirect,
    google_enabled,
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.calendar_gateway import CalendarToolError
from mindnest_api.deps import (
    AuthUser,
    CalendarGatewayDep,
    GoogleDep,
    LimiterDep,
    UserDbDep,
    client_ip,
    get_current_user,
)
from mindnest_api.errors import AppError
from mindnest_api.routes.google_auth import safe_next
from mindnest_api.vault import decrypt, encrypt

router = APIRouter(prefix="/integrations/google-calendar", tags=["integrations"])
log = logging.getLogger("mindnest.gcal")

FLOW_COOKIE = "mindnest_gcal"
FLOW_PATH = "/api/v1/integrations/google-calendar"


# ------------------------------------------------------------------------------ schemas


class StatusOut(BaseModel):
    available: bool
    connected: bool
    needs_reconnect: bool = False
    connected_at: datetime | None = None
    last_synced_at: datetime | None = None
    synced_items: int = 0


class ChangeOut(BaseModel):
    action: Literal["create", "update", "delete"]
    source_type: str
    source_id: UUID
    day: str
    summary: str


class PreviewOut(BaseModel):
    changes: list[ChangeOut]


class ItemRef(BaseModel):
    source_type: Literal["exam", "assignment", "task", "event"]
    source_id: UUID


class SyncIn(BaseModel):
    items: list[ItemRef] = Field(min_length=1, max_length=MAX_SYNC_ITEMS)


class FailedItem(BaseModel):
    source_type: str
    source_id: UUID
    error: str


class SyncOut(BaseModel):
    created: int
    updated: int
    deleted: int
    failed: list[FailedItem]


class RetryIn(BaseModel):
    # Empty: every item that failed.
    items: list[ItemRef] = Field(default_factory=list, max_length=MAX_SYNC_ITEMS)


class SyncItemOut(BaseModel):
    source_type: str
    source_id: UUID
    # waiting: not sent yet or changed since; failed: the last send did not work.
    state: Literal["pending", "failed"]
    action: Literal["create", "update", "delete"]
    day: str
    summary: str
    error: str | None = None
    attempts: int = 0
    last_failed_at: datetime | None = None


class StateOut(BaseModel):
    synced: int
    pending: int
    failed: int
    items: list[SyncItemOut]


# ------------------------------------------------------------------------------ status


@router.get("", response_model=StatusOut)
async def status(_user: AuthUser, db: UserDbDep) -> StatusOut:
    available = google_enabled(get_settings())
    async with db.session() as session:
        link = (
            (
                await session.execute(
                    text("SELECT needs_reconnect, connected_at, last_synced_at FROM google_calendar_links")
                )
            )
            .mappings()
            .first()
        )
        count = (await session.execute(text("SELECT count(*) FROM calendar_sync_items"))).scalar_one()
    if link is None:
        return StatusOut(available=available, connected=False)
    return StatusOut(
        available=available, connected=True, needs_reconnect=link["needs_reconnect"],
        connected_at=link["connected_at"], last_synced_at=link["last_synced_at"], synced_items=int(count),
    )


# ------------------------------------------------------------------------------ connecting


def _cookie(response: Response, value: str, max_age: int) -> None:
    response.set_cookie(
        FLOW_COOKIE, value, max_age=max_age, httponly=True, samesite="lax",
        secure=get_settings().environment != "development", path=FLOW_PATH,
    )


def _back(code: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{get_settings().web_base_url.rstrip('/')}/calendar?gcal={code}", status_code=303
    )
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/start")
async def start(
    request: Request, user: AuthUser, limiter: LimiterDep,
    next: Annotated[str | None, Query(max_length=300)] = None,
) -> Response:
    settings = get_settings()
    if not google_enabled(settings):
        raise AppError(503, "google_not_configured", "Google is not set up on this server yet.")
    await limiter.check(f"gcal:start:{user.id}", 20, 900)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = authorize_url(
        client_id=settings.google_client_id, redirect_uri=google_calendar_redirect(settings),
        state=state, challenge=challenge, nonce=nonce, scope=SCOPE,
        extra={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "false"},
    )
    response = RedirectResponse(url, status_code=303)
    blob = seal(
        settings.secret_key,
        {"s": state, "v": verifier, "u": str(user.id), "next": safe_next(next, "/calendar")},
    )
    _cookie(response, blob, 600)
    return response


@router.get("/callback")
async def callback(
    request: Request, google: GoogleDep, gateway: CalendarGatewayDep, limiter: LimiterDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    settings = get_settings()
    if not google_enabled(settings):
        return _back("error_not_configured")
    await limiter.check(f"gcal:callback:{client_ip(request)}", 30, 900)
    flow = unseal(settings.secret_key, request.cookies.get(FLOW_COOKIE))
    expected = flow.get("s") if flow else None
    if flow is None or not isinstance(expected, str) or not state or not secrets.compare_digest(state, expected):
        return _back("error_failed")
    # The student who started this must still be the one signed in.
    try:
        user = await get_current_user(request)
    except AppError:
        return _back("error_signin")
    if str(user.id) != flow.get("u"):
        return _back("error_failed")
    if error or not code:
        return _back("cancelled")

    try:
        tokens = await google.exchange_code(code, str(flow["v"]), google_calendar_redirect(settings))
        refresh = tokens.get("refresh_token")
        access = tokens.get("access_token")
        if not isinstance(refresh, str) or not refresh or not isinstance(access, str):
            return _back("error_no_refresh")
        if SCOPE not in str(tokens.get("scope", "")).split():
            return _back("error_scope")
    except GoogleError as exc:
        log.warning("google calendar connect failed: %s", exc)
        return _back("error_failed")

    # Save the link first (the calendar server reads it), then have the calendar server make the
    # "MindNest AI" calendar on the student's own Google Calendar. If that fails, undo the link.
    async with user_session(request.app.state.session_factory, user.id) as session:
        await session.execute(
            text(
                "INSERT INTO google_calendar_links (user_id, refresh_token_enc, scope, calendar_id) "
                "VALUES (:u, :t, :s, NULL) ON CONFLICT (user_id) DO UPDATE SET "
                "refresh_token_enc = :t, scope = :s, calendar_id = NULL, needs_reconnect = false, "
                "connected_at = now()"
            ),
            {"u": user.id, "t": encrypt(settings.secret_key, refresh), "s": SCOPE},
        )
        # A new calendar starts empty, so anything remembered about the old one is stale.
        await session.execute(text("DELETE FROM calendar_sync_items"))
        await session.execute(text("DELETE FROM calendar_sync_failures"))
    try:
        await gateway.ensure_calendar(user.id)
    except CalendarToolError as exc:
        log.warning("could not make the MindNest calendar: %s", exc.code)
        async with user_session(request.app.state.session_factory, user.id) as session:
            await session.execute(text("DELETE FROM google_calendar_links"))
        await google.revoke(refresh)
        return _back("error_calendar_api" if exc.code == "google_403" else "error_failed")
    return _back("connected")


# ------------------------------------------------------------------------------ what to send


async def _candidates(session: AsyncSession, user: AuthUser) -> list[Candidate]:
    today = local_today(user.timezone, datetime.now(UTC))
    zone = local_zone(user.timezone).key
    lang = user.ui_language
    found: list[Candidate] = []
    for r in (
        await session.execute(
            text("SELECT id, title, exam_on FROM exams WHERE exam_on >= :t"), {"t": today}
        )
    ).mappings():
        found.append(Candidate("exam", str(r["id"]), r["exam_on"], summary_for(lang, "exam", r["title"])))
    for r in (
        await session.execute(
            text(
                "SELECT id, title, (due_at AT TIME ZONE :tz)::date AS day FROM assignments "
                "WHERE status <> 'done' AND due_at IS NOT NULL AND (due_at AT TIME ZONE :tz)::date >= :t"
            ),
            {"tz": zone, "t": today},
        )
    ).mappings():
        found.append(Candidate("assignment", str(r["id"]), r["day"], summary_for(lang, "assignment", r["title"])))
    for r in (
        await session.execute(
            text(
                "SELECT id, title, template, params, planned_for, minutes FROM study_tasks "
                "WHERE status = 'todo' AND planned_for >= :t"
            ),
            {"t": today},
        )
    ).mappings():
        found.append(
            Candidate("task", str(r["id"]), r["planned_for"], summary_for(lang, "task", r["title"], r["minutes"]))
        )
    # The student's own events, only the ones they chose to send to Google.
    for r in (
        await session.execute(
            text(
                "SELECT id, title, notes, day, start_time, minutes FROM calendar_events "
                "WHERE sync_to_google AND day >= :t"
            ),
            {"t": today},
        )
    ).mappings():
        found.append(
            Candidate(
                "event", str(r["id"]), r["day"], r["title"][:200], r["notes"], start_time=r["start_time"],
                minutes=r["minutes"], timezone=zone, transparent=r["start_time"] == "",
            )
        )
    return found


async def _synced(session: AsyncSession) -> dict[tuple[str, str], Synced]:
    rows = (
        await session.execute(
            text("SELECT source_type, source_id, day, fingerprint, google_event_id FROM calendar_sync_items")
        )
    ).mappings()
    return {
        (r["source_type"], str(r["source_id"])): Synced(r["day"], r["fingerprint"], r["google_event_id"])
        for r in rows
    }


async def _changes(session: AsyncSession, user: AuthUser) -> list[Change]:
    today = local_today(user.timezone, datetime.now(UTC))
    return diff(await _candidates(session, user), await _synced(session), today)


async def _link(session: AsyncSession) -> Any:
    link = (
        (
            await session.execute(
                text("SELECT refresh_token_enc, calendar_id, needs_reconnect FROM google_calendar_links")
            )
        )
        .mappings()
        .first()
    )
    if link is None:
        raise AppError(409, "gcal_not_connected", "Connect Google Calendar first.")
    if link["needs_reconnect"]:
        raise AppError(409, "gcal_reconnect", "Please connect Google Calendar again.")
    return link


@router.get("/preview", response_model=PreviewOut)
async def preview(user: AuthUser, db: UserDbDep) -> PreviewOut:
    async with db.session() as session:
        await _link(session)
        changes = await _changes(session, user)
    return PreviewOut(
        changes=[
            ChangeOut(
                action=c.action, source_type=c.source_type, source_id=UUID(c.source_id),
                day=c.day.isoformat(), summary=c.summary,
            )
            for c in changes
        ]
    )


# ------------------------------------------------------------------------------ sending


def _tool_error(exc: CalendarToolError) -> AppError:
    if exc.code == "gcal_reconnect":
        return AppError(409, "gcal_reconnect", "Please connect Google Calendar again.")
    if exc.code == "gcal_not_connected":
        return AppError(409, "gcal_not_connected", "Connect Google Calendar first.")
    if exc.code == "rate_limited":
        return AppError(429, "rate_limited", "Google is busy. Try again in a minute.")
    return AppError(503, "calendar_unavailable", "The calendar service could not be reached. Try again soon.")


def _op(change: Change, link: str) -> Op:
    if change.action == "delete":
        return Op(action="delete", event_id=change.event_id or "")
    assert change.candidate is not None
    return Op(
        action=change.action, event_id=change.event_id or "", event=event_in(change.candidate, link),
        recreate_missing=True,  # the student may have deleted it in Google; put it back
        # Sending the same version twice (a retry after a timeout) never adds a second event.
        request_key=change.candidate.request_key if change.action == "create" else "",
    )


async def _failures(session: AsyncSession) -> dict[tuple[str, str], Any]:
    rows = (
        await session.execute(
            text(
                "SELECT source_type, source_id, action, error, attempts, last_failed_at "
                "FROM calendar_sync_failures"
            )
        )
    ).mappings()
    return {(r["source_type"], str(r["source_id"])): r for r in rows}


async def sync_states(session: AsyncSession, user: AuthUser) -> dict[tuple[str, str], str]:
    """For each exam, assignment, task or event: synced, pending or failed. Empty when Google
    Calendar is not connected."""
    linked = (
        await session.execute(text("SELECT 1 FROM google_calendar_links WHERE NOT needs_reconnect"))
    ).first()
    if linked is None:
        return {}
    failures = await _failures(session)
    states = dict.fromkeys(await _synced(session), "synced")
    for change in await _changes(session, user):
        states[change.key] = "failed" if change.key in failures else "pending"
    return states


@router.get("/state", response_model=StateOut)
async def state(user: AuthUser, db: UserDbDep) -> StateOut:
    """What is on Google, what is waiting to be sent and what failed (with why)."""
    async with db.session() as session:
        await _link(session)
        changes = await _changes(session, user)
        synced = await _synced(session)
        failures = await _failures(session)
    items: list[SyncItemOut] = []
    for change in changes:
        failure = failures.get(change.key)
        items.append(
            SyncItemOut(
                source_type=change.source_type, source_id=UUID(change.source_id), state="failed" if failure else "pending",
                action=change.action, day=change.day.isoformat(), summary=change.summary,
                error=failure["error"] if failure else None, attempts=failure["attempts"] if failure else 0,
                last_failed_at=failure["last_failed_at"] if failure else None,
            )
        )
    items.sort(key=lambda i: (i.state != "failed", i.day))
    changed = {c.key for c in changes}
    return StateOut(
        synced=len([key for key in synced if key not in changed]),
        pending=len([i for i in items if i.state == "pending"]),
        failed=len([i for i in items if i.state == "failed"]),
        items=items,
    )


async def _send(
    chosen: list[Change], user: AuthUser, db: UserDbDep, gateway: CalendarGatewayDep
) -> SyncOut:
    """Send these changes. What worked is remembered, what did not is kept with its reason so it
    can be retried; an item that works later clears its failure."""
    if not chosen:
        return SyncOut(created=0, updated=0, deleted=0, failed=[])
    base = get_settings().web_base_url.rstrip("/")

    def link_for(change: Change) -> str:
        return f"{base}/calendar" if change.source_type == "event" else f"{base}/planner"

    try:
        results = await gateway.apply_changes(user.id, [_op(c, link_for(c)) for c in chosen])
    except CalendarToolError as exc:
        raise _tool_error(exc) from None
    if len(results) != len(chosen):
        raise AppError(503, "calendar_unavailable", "The calendar service answered unexpectedly.")
    for result in results:
        if not result.get("ok") and result.get("error") in ("gcal_reconnect", "gcal_not_connected"):
            raise _tool_error(CalendarToolError(str(result["error"])))

    created = updated = deleted = 0
    failed: list[FailedItem] = []
    async with db.session() as session:
        for change, result in zip(chosen, results, strict=True):
            if not result.get("ok"):
                reason = str(result.get("error") or "calendar_error")[:80]
                failed.append(FailedItem(
                    source_type=change.source_type, source_id=UUID(change.source_id), error=reason,
                ))
                await session.execute(
                    text(
                        "INSERT INTO calendar_sync_failures (user_id, source_type, source_id, action, error) "
                        "VALUES (:u, :t, :i, :a, :e) ON CONFLICT (user_id, source_type, source_id) DO UPDATE "
                        "SET action = :a, error = :e, attempts = calendar_sync_failures.attempts + 1, "
                        "last_failed_at = now()"
                    ),
                    {"u": user.id, "t": change.source_type, "i": change.source_id, "a": change.action, "e": reason},
                )
                continue
            await session.execute(
                text("DELETE FROM calendar_sync_failures WHERE source_type = :t AND source_id = :i"),
                {"t": change.source_type, "i": change.source_id},
            )
            if change.action == "delete":
                await session.execute(
                    text("DELETE FROM calendar_sync_items WHERE source_type = :t AND source_id = :i"),
                    {"t": change.source_type, "i": change.source_id},
                )
                deleted += 1
                continue
            assert change.candidate is not None and result.get("event_id")
            await session.execute(
                text(
                    "INSERT INTO calendar_sync_items (user_id, source_type, source_id, day, fingerprint, google_event_id) "
                    "VALUES (:u, :t, :i, :d, :f, :e) ON CONFLICT (user_id, source_type, source_id) DO UPDATE SET "
                    "day = :d, fingerprint = :f, google_event_id = :e, synced_at = now()"
                ),
                {"u": user.id, "t": change.source_type, "i": change.source_id, "d": change.day,
                 "f": change.candidate.fingerprint, "e": str(result["event_id"])},
            )
            created += change.action == "create"
            updated += change.action == "update"
        await session.execute(text("UPDATE google_calendar_links SET last_synced_at = now()"))
    return SyncOut(created=created, updated=updated, deleted=deleted, failed=failed)


@router.post("/sync", response_model=SyncOut)
async def sync(
    body: SyncIn, user: AuthUser, db: UserDbDep, gateway: CalendarGatewayDep, limiter: LimiterDep,
) -> SyncOut:
    await limiter.check(f"gcal:sync:{user.id}", 30, 3600)
    async with db.session() as session:
        await _link(session)
        proposed = {c.key: c for c in await _changes(session, user)}
    # Only changes the server itself proposes, and only the ones the student ticked.
    chosen = [proposed[(i.source_type, str(i.source_id))] for i in body.items
              if (i.source_type, str(i.source_id)) in proposed]
    return await _send(chosen, user, db, gateway)


@router.post("/retry", response_model=SyncOut)
async def retry(
    body: RetryIn, user: AuthUser, db: UserDbDep, gateway: CalendarGatewayDep, limiter: LimiterDep,
) -> SyncOut:
    """Send again what failed last time. An item that no longer needs sending (the student deleted
    it, or it already matches Google) just loses its failure."""
    await limiter.check(f"gcal:sync:{user.id}", 30, 3600)
    async with db.session() as session:
        await _link(session)
        proposed = {c.key: c for c in await _changes(session, user)}
        failures = await _failures(session)
        for key in [k for k in failures if k not in proposed]:
            await session.execute(
                text("DELETE FROM calendar_sync_failures WHERE source_type = :t AND source_id = :i"),
                {"t": key[0], "i": key[1]},
            )
    asked = {(i.source_type, str(i.source_id)) for i in body.items}
    chosen = [change for key, change in proposed.items() if key in failures and (not asked or key in asked)]
    return await _send(chosen, user, db, gateway)


# ------------------------------------------------------------------------------ disconnecting


@router.delete("", status_code=204)
async def disconnect(
    user: AuthUser, db: UserDbDep, google: GoogleDep, gateway: CalendarGatewayDep,
    remove_events: bool = False,
) -> Response:
    settings = get_settings()
    async with db.session() as session:
        link = (
            (await session.execute(text("SELECT refresh_token_enc, calendar_id FROM google_calendar_links")))
            .mappings()
            .first()
        )
    if link is not None:
        try:
            refresh = decrypt(settings.secret_key, link["refresh_token_enc"])
        except AppError:
            refresh = ""
        if remove_events and link["calendar_id"]:
            try:
                await gateway.remove_calendar(user.id)
            except CalendarToolError:
                log.warning("could not remove the MindNest calendar while disconnecting")
        if refresh:
            await google.revoke(refresh)
    async with db.session() as session:
        await session.execute(text("DELETE FROM calendar_sync_items"))
        await session.execute(text("DELETE FROM calendar_sync_failures"))
        await session.execute(text("DELETE FROM google_calendar_links"))
    return Response(status_code=204)
