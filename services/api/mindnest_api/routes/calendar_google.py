"""The student's Google events, for the Calendar page.

Only the calendar MindNest keeps in the student's Google account is read (see the Google
Calendar integration), and events MindNest itself sent from an exam, assignment or task are left
out, because the Calendar page already shows those from their own records. What remains are
events added from the chat assistant or straight in Google.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from mindnest_core.plannerlogic import local_zone
from pydantic import BaseModel
from sqlalchemy import text

from mindnest_api.calendar_gateway import CalendarToolError
from mindnest_api.deps import AuthUser, CalendarGatewayDep, UserDbDep
from mindnest_api.errors import AppError

router = APIRouter(tags=["calendar"])
MAX_DAYS = 62
MAX_EVENTS = 200


class GoogleEvent(BaseModel):
    id: str
    summary: str
    day: date
    start_time: str
    minutes: int
    all_day: bool
    link: str


class GoogleEventsOut(BaseModel):
    connected: bool
    # A short code (for example "gcal_reconnect") when Google could not be read; the page still works.
    error: str | None = None
    events: list[GoogleEvent]


@router.get("/calendar/google", response_model=GoogleEventsOut)
async def google_events(
    user: AuthUser,
    db: UserDbDep,
    gateway: CalendarGatewayDep,
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
) -> GoogleEventsOut:
    if last < first or (last - first).days > MAX_DAYS:
        raise AppError(422, "validation_error", f"Choose a range of at most {MAX_DAYS} days.")
    async with db.session() as session:
        link = (
            (await session.execute(text("SELECT calendar_id, needs_reconnect FROM google_calendar_links")))
            .mappings()
            .first()
        )
    if link is None or not link["calendar_id"]:
        return GoogleEventsOut(connected=False, events=[])
    if link["needs_reconnect"]:
        return GoogleEventsOut(connected=True, error="gcal_reconnect", events=[])
    try:
        raw = await gateway.list_events(
            user.id, first.isoformat(), last.isoformat(), local_zone(user.timezone).key, MAX_EVENTS
        )
    except CalendarToolError as exc:
        return GoogleEventsOut(connected=True, error=exc.code, events=[])
    events = [
        GoogleEvent(
            id=e["id"], summary=e["summary"], day=e["day"], start_time=e["start_time"],
            minutes=e["minutes"], all_day=e["all_day"], link=e["link"],
        )
        for e in raw
        if e.get("source_type") not in ("exam", "assignment", "task")
        and first.isoformat() <= str(e.get("day") or "") <= last.isoformat()
    ]
    return GoogleEventsOut(connected=True, events=events)
