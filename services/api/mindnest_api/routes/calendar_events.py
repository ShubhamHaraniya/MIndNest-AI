"""Events the student adds to their own calendar (a lecture, a lab, an appointment).

They sit beside exams, assignment deadlines and study tasks on the Calendar page, and can be sent
to Google Calendar like the others. Adding the same event twice never gives two: the browser
names each request, and two events with the same title at the same time are refused.
"""

import re
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.gcal import sync_states

router = APIRouter(tags=["calendar"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MIN_MINUTES, MAX_MINUTES = 5, 24 * 60


def _time(value: str | None) -> str | None:
    if value and not TIME.match(value):
        raise ValueError("start_time must look like 18:30, or be empty for an all-day event")
    return value


class EventIn(BaseModel):
    title: Title
    notes: Notes = ""
    day: date
    start_time: str = ""
    minutes: int = Field(default=60, ge=MIN_MINUTES, le=MAX_MINUTES)
    subject_id: UUID | None = None
    sync_to_google: bool = False
    # Names this request: sending it again returns the event it made instead of adding another.
    request_key: str | None = None

    @field_validator("start_time")
    @classmethod
    def _t(cls, value: str) -> str:
        return _time(value) or ""

    @field_validator("request_key")
    @classmethod
    def _k(cls, value: str | None) -> str | None:
        if value is not None and not KEY.match(value):
            raise ValueError("request_key must be 8 to 64 letters, digits, - or _")
        return value


class EventPatch(BaseModel):
    title: Title | None = None
    notes: Notes | None = None
    day: date | None = None
    start_time: str | None = None
    minutes: int | None = Field(default=None, ge=MIN_MINUTES, le=MAX_MINUTES)
    subject_id: UUID | None = None
    sync_to_google: bool | None = None

    @field_validator("start_time")
    @classmethod
    def _t(cls, value: str | None) -> str | None:
        return _time(value)


class EventOut(BaseModel):
    id: UUID
    title: str
    notes: str
    day: date
    start_time: str
    minutes: int
    subject_id: UUID | None
    subject_name: str | None
    sync_to_google: bool
    # synced | pending | failed | None (not meant for Google, or Google is not connected)
    sync: str | None


_SQL = """
  SELECT e.id, e.title, e.notes, e.day, e.start_time, e.minutes, e.subject_id, e.sync_to_google,
         s.name AS subject_name
  FROM calendar_events e LEFT JOIN subjects s ON s.id = e.subject_id
"""


async def _row(session: AsyncSession, event_id: UUID) -> Any:
    row = (await session.execute(text(f"{_SQL} WHERE e.id = :id"), {"id": event_id})).mappings().first()
    if row is None:
        raise AppError(404, "not_found", "Event not found.")
    return row


async def _out(session: AsyncSession, user: AuthUser, row: Any) -> EventOut:
    states = await sync_states(session, user) if row["sync_to_google"] else {}
    return EventOut(
        id=row["id"], title=row["title"], notes=row["notes"], day=row["day"], start_time=row["start_time"],
        minutes=row["minutes"], subject_id=row["subject_id"], subject_name=row["subject_name"],
        sync_to_google=row["sync_to_google"], sync=states.get(("event", str(row["id"]))),
    )


async def _check_subject(session: AsyncSession, subject_id: UUID | None) -> None:
    if subject_id is None:
        return
    found = (
        await session.execute(
            text("SELECT 1 FROM subjects WHERE id = :s AND archived_at IS NULL"), {"s": subject_id}
        )
    ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Subject not found.")


@router.post("/calendar/events", status_code=201, response_model=EventOut)
async def create_event(body: EventIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> EventOut:
    await limiter.check(f"cal-event-create:{user.id}", 120, 3600)
    async with db.session() as session:
        await _check_subject(session, body.subject_id)
        event_id = (
            await session.execute(
                text(
                    "INSERT INTO calendar_events (user_id, subject_id, title, notes, day, start_time, minutes, "
                    "sync_to_google, request_key) VALUES (:u, :s, :t, :n, :d, :st, :m, :g, :k) "
                    "ON CONFLICT DO NOTHING RETURNING id"
                ),
                {
                    "u": user.id, "s": body.subject_id, "t": body.title, "n": body.notes, "d": body.day,
                    "st": body.start_time, "m": body.minutes, "g": body.sync_to_google, "k": body.request_key,
                },
            )
        ).scalar_one_or_none()
        if event_id is None:
            # Either this very request was made before (return what it made), or another event
            # has the same title, day and time.
            if body.request_key:
                earlier = (
                    await session.execute(
                        text("SELECT id FROM calendar_events WHERE request_key = :k"), {"k": body.request_key}
                    )
                ).scalar_one_or_none()
                if earlier is not None:
                    return await _out(session, user, await _row(session, earlier))
            raise AppError(409, "event_duplicate", "You already have an event with this name at this time.")
        return await _out(session, user, await _row(session, event_id))


@router.patch("/calendar/events/{event_id}", response_model=EventOut)
async def update_event(event_id: UUID, body: EventPatch, user: AuthUser, db: UserDbDep) -> EventOut:
    sent = body.model_fields_set
    for name in ("title", "notes", "day", "start_time", "minutes", "sync_to_google"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
    async with db.session() as session:
        row = await _row(session, event_id)
        if "subject_id" in changes:
            await _check_subject(session, changes["subject_id"])
        if changes:
            title = changes.get("title", row["title"])
            day = changes.get("day", row["day"])
            start = changes.get("start_time", row["start_time"])
            twin = (
                await session.execute(
                    text(
                        "SELECT 1 FROM calendar_events WHERE lower(title) = lower(:t) AND day = :d "
                        "AND start_time = :s AND id <> :id"
                    ),
                    {"t": title, "d": day, "s": start, "id": event_id},
                )
            ).first()
            if twin is not None:
                raise AppError(409, "event_duplicate", "You already have an event with this name at this time.")
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            await session.execute(
                text(f"UPDATE calendar_events SET {sets}, updated_at = now() WHERE id = :id"),
                {**changes, "id": event_id},
            )
        return await _out(session, user, await _row(session, event_id))


@router.delete("/calendar/events/{event_id}", status_code=204)
async def delete_event(event_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(text("DELETE FROM calendar_events WHERE id = :id"), {"id": event_id})
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Event not found.")
    return Response(status_code=204)
