"""Which MindNest items to put on the student's Google Calendar, and what the events look like.

Pure functions. The student approves every change before anything is sent; this module only
works out what the changes would be. Event text comes from the student's own data in the
database, never from the browser.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from mindnest_core.calevent import EventIn, google_body

SOURCE_TYPES = ("exam", "assignment", "task", "event")
MAX_SYNC_ITEMS = 40
CALENDAR_NAME = "MindNest AI"

LABELS = {
    "en": {"exam": "Exam", "assignment": "Due", "task": "Study"},
    "hi": {"exam": "परीक्षा", "assignment": "जमा करना", "task": "अध्ययन"},
    "gu": {"exam": "પરીક્ષા", "assignment": "સબમિટ કરવું", "task": "અભ્યાસ"},
}

Action = Literal["create", "update", "delete"]


@dataclass(frozen=True)
class Candidate:
    source_type: str
    source_id: str
    day: date
    summary: str
    description: str = ""
    # Only the student's own events have a time of day; everything else is an all-day marker that
    # does not block time.
    start_time: str = ""
    minutes: int = 60
    timezone: str = "UTC"
    transparent: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_type, self.source_id)

    @property
    def fingerprint(self) -> str:
        parts: list[Any] = [self.summary, self.day.isoformat(), self.description]
        if self.source_type == "event":  # other kinds keep the fingerprints they already have
            parts += [self.start_time, self.minutes, self.timezone, self.transparent]
        raw = json.dumps(parts, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def request_key(self) -> str:
        """Names this version of this item, so sending it twice never adds two events to Google."""
        return f"gcal:{self.source_type}:{self.source_id}:{self.fingerprint}"


@dataclass(frozen=True)
class Synced:
    day: date
    fingerprint: str
    event_id: str


@dataclass(frozen=True)
class Change:
    action: Action
    source_type: str
    source_id: str
    day: date
    summary: str
    event_id: str | None = None
    candidate: Candidate | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_type, self.source_id)


def label(language: str, source_type: str) -> str:
    return LABELS.get(language, LABELS["en"])[source_type]


def summary_for(language: str, source_type: str, title: str, minutes: int | None = None) -> str:
    text = f"{label(language, source_type)}: {title.strip()}"
    if minutes:
        text += f" ({minutes} min)"
    return text[:200]


def event_body(candidate: Candidate, link: str) -> dict[str, Any]:
    """The Google Calendar event for one item: an all-day event that does not block time."""
    return google_body(event_in(candidate, link))


def event_in(candidate: Candidate, link: str) -> EventIn:
    """The same event in MindNest's own shape, which is what the calendar server is sent."""
    description = candidate.description.strip()
    description = f"{description}\n\n{link}" if description else link
    return EventIn(
        summary=candidate.summary, description=description[:2000], day=candidate.day,
        start_time=candidate.start_time, minutes=candidate.minutes, timezone=candidate.timezone,
        transparent=candidate.transparent, source_type=candidate.source_type, source_id=candidate.source_id,
    )


def diff(
    candidates: Iterable[Candidate], synced: Mapping[tuple[str, str], Synced], today: date
) -> list[Change]:
    """What would change on the calendar.

    A candidate that was never sent is a create; one that was sent but now reads differently is an
    update; one that was sent and is no longer wanted (deleted, finished, skipped) is a delete.
    Events for days already past are left alone.
    """
    changes: list[Change] = []
    wanted: set[tuple[str, str]] = set()
    for candidate in candidates:
        wanted.add(candidate.key)
        sent = synced.get(candidate.key)
        if sent is None:
            changes.append(Change("create", *candidate.key, candidate.day, candidate.summary, None, candidate))
        elif sent.fingerprint != candidate.fingerprint:
            changes.append(
                Change("update", *candidate.key, candidate.day, candidate.summary, sent.event_id, candidate)
            )
    for key, sent in synced.items():
        if key not in wanted and sent.day >= today:
            changes.append(Change("delete", *key, sent.day, "", sent.event_id, None))
    changes.sort(key=lambda c: (c.day, c.source_type, c.source_id))
    return changes
