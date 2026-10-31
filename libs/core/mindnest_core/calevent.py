"""One calendar event, as MindNest describes it, and how it becomes a Google Calendar event.

The API and the calendar MCP server share this model. The API only ever sends this narrow shape
(never a raw Google event), and the server turns it into Google's format itself, so nothing that
reaches Google can carry guests, video-call links or other fields MindNest does not mean to set.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SOURCE = re.compile(r"^[A-Za-z0-9_-]{0,64}$")
MIN_MINUTES = 5
MAX_MINUTES = 24 * 60
DEFAULT_MINUTES = 60


class EventIn(BaseModel):
    """What the student asked for. Without `start_time` the event is an all-day event."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    day: date
    start_time: str = Field(default="", description="HH:MM on a 24-hour clock; empty for an all-day event.")
    minutes: int = Field(default=DEFAULT_MINUTES, ge=MIN_MINUTES, le=MAX_MINUTES)
    timezone: str = Field(default="UTC", max_length=64)
    transparent: bool = Field(default=False, description="True: shown on the calendar without blocking the time.")
    source_type: str = Field(default="", max_length=20)
    source_id: str = Field(default="", max_length=64)

    @field_validator("start_time")
    @classmethod
    def _time(cls, value: str) -> str:
        if value and not TIME.match(value):
            raise ValueError("start_time must look like 18:30")
        return value

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("unknown time zone") from exc
        return value

    @field_validator("source_type", "source_id")
    @classmethod
    def _source(cls, value: str) -> str:
        if not SOURCE.match(value):
            raise ValueError("source ids may only hold letters, digits, - and _")
        return value

    @property
    def all_day(self) -> bool:
        return not self.start_time


def google_body(event: EventIn) -> dict[str, Any]:
    """The Google Calendar API body for an event."""
    if event.all_day:
        start: dict[str, str] = {"date": event.day.isoformat()}
        # Google's end date is exclusive: a one-day event ends the next day.
        end: dict[str, str] = {"date": (event.day + timedelta(days=1)).isoformat()}
    else:
        hour, minute = (int(part) for part in event.start_time.split(":"))
        begins = datetime(event.day.year, event.day.month, event.day.day, hour, minute)
        finishes = begins + timedelta(minutes=event.minutes)
        start = {"dateTime": begins.isoformat(timespec="seconds"), "timeZone": event.timezone}
        end = {"dateTime": finishes.isoformat(timespec="seconds"), "timeZone": event.timezone}
    private = {"mindnest": "1"}
    if event.source_type:
        private["source"] = event.source_type
    if event.source_id:
        private["id"] = event.source_id
    return {
        "summary": event.summary,
        "description": event.description,
        "start": start,
        "end": end,
        "transparency": "transparent" if event.transparent else "opaque",
        "extendedProperties": {"private": private},
    }


def read_event(raw: dict[str, Any]) -> dict[str, Any]:
    """A Google event, reduced to what MindNest shows and edits."""
    start = raw.get("start") or {}
    end = raw.get("end") or {}
    all_day = "date" in start
    private = (raw.get("extendedProperties") or {}).get("private") or {}
    day = str(start.get("date") or str(start.get("dateTime", ""))[:10])
    start_time = "" if all_day else str(start.get("dateTime", ""))[11:16]
    minutes = DEFAULT_MINUTES
    if not all_day:
        try:
            minutes = int(
                (datetime.fromisoformat(str(end["dateTime"])) - datetime.fromisoformat(str(start["dateTime"])))
                .total_seconds() // 60
            )
        except (KeyError, ValueError):
            minutes = DEFAULT_MINUTES
    return {
        "id": str(raw.get("id", "")),
        "summary": str(raw.get("summary", "") or "")[:200],
        "description": str(raw.get("description", "") or "")[:2000],
        "day": day,
        "start_time": start_time,
        "minutes": minutes,
        "all_day": all_day,
        "status": str(raw.get("status", "confirmed")),
        "link": str(raw.get("htmlLink", "") or ""),
        "timezone": str(start.get("timeZone", "") or ""),
        "mindnest": bool(private.get("mindnest")),
        "transparent": raw.get("transparency") == "transparent",
        "source_type": str(private.get("source", "") or "")[:20],
        "source_id": str(private.get("id", "") or "")[:64],
    }


class Op(BaseModel):
    """One change in a batch (used by the Calendar page's sync)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["create", "update", "delete"]
    event_id: str = Field(default="", max_length=200)
    event: EventIn | None = None
    # For an update: if Google no longer has the event (the student deleted it), add it again.
    recreate_missing: bool = False
    # For a create: asking twice with the same key never adds two events (the key names the event).
    request_key: str = Field(default="", max_length=200)


class EventEdits(BaseModel):
    """Changes a student makes to a proposed event before approving it. Only what was sent is
    changed; `start_time` of "" turns a timed event into an all-day one."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    day: date | None = None
    start_time: str | None = None
    minutes: int | None = Field(default=None, ge=MIN_MINUTES, le=MAX_MINUTES)

    @field_validator("start_time")
    @classmethod
    def _time(cls, value: str | None) -> str | None:
        if value and not TIME.match(value):
            raise ValueError("start_time must look like 18:30")
        return value


def apply_edits(event: EventIn, edits: EventEdits | None) -> EventIn:
    """The event with the student's edits applied (validated again as a whole)."""
    if edits is None:
        return event
    changed = {k: v for k, v in edits.model_dump(exclude_unset=True).items() if v is not None}
    return EventIn.model_validate({**event.model_dump(), **changed})
