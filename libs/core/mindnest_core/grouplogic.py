"""Rules for study groups: join codes and limits. Pure functions, no database."""

import re
import secrets
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal

# No 0/O/1/I/L, so a code read aloud or from a screenshot is hard to get wrong.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10

MAX_GROUPS_PER_USER = 10
MAX_MEMBERS = 500
MAX_ITEMS = 500
# Different students who report a file before it is hidden until the group owner decides.
HIDE_AT_REPORTS = 3

REPORT_REASONS = ("copyright", "inappropriate", "wrong_content", "other")

_SEPARATORS = re.compile(r"[\s\-_.]+")


def new_join_code() -> str:
    """A random code: about 50 bits, so guessing one is not realistic even with many tries."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """What a student typed, as a stored code, or None if it cannot be a code.

    Spaces and dashes are ignored and case does not matter, so "abcde-fgh23" and "ABCDEFGH23" match.
    """
    cleaned = _SEPARATORS.sub("", raw or "").upper()
    if len(cleaned) != CODE_LENGTH or any(ch not in ALPHABET for ch in cleaned):
        return None
    return cleaned


def display_code(code: str) -> str:
    """ABCDE-FGH23 style, for reading and sharing."""
    return f"{code[: CODE_LENGTH // 2]}-{code[CODE_LENGTH // 2 :]}"


# ------------------------------------------------------------------ roles and what each may do

ROLES = ("owner", "admin", "member")
INVITE_ROLES = ("admin", "member")


def is_admin(role: str | None) -> bool:
    """Owners and admins run the group: invite, remove members, hide or restore files, and
    moderate notes, discussions and sessions."""
    return role in ("owner", "admin")


def can_remove_member(actor: str | None, target: str | None) -> bool:
    """An owner removes admins and members, an admin removes members; nobody removes the owner."""
    if actor == "owner":
        return target in ("admin", "member")
    if actor == "admin":
        return target == "member"
    return False


def can_set_role(actor: str | None, target: str | None, new_role: str) -> bool:
    """Only the owner makes someone an admin or takes it back, and the owner's own role is fixed."""
    return actor == "owner" and target in ("admin", "member") and new_role in INVITE_ROLES


def can_change(role: str | None, is_author: bool) -> bool:
    """Edit or delete a note, post or session: its author, or a group admin."""
    return is_author or is_admin(role)


# ------------------------------------------------------------------ invitations

INVITE_DAYS = 14
MAX_PENDING_INVITES = 50
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")


def normalize_email(raw: str) -> str | None:
    """An email address as it is compared (lower case), or None if it cannot be one."""
    cleaned = (raw or "").strip().lower()
    if len(cleaned) > 254 or not _EMAIL.match(cleaned):
        return None
    return cleaned


# ------------------------------------------------------------------ notes, discussions, sessions

MAX_NOTES = 300
MAX_THREADS = 300
MAX_POSTS_PER_THREAD = 500
MAX_SESSIONS = 200
MIN_SESSION_MINUTES, MAX_SESSION_MINUTES = 15, 720
RSVPS = ("going", "maybe", "declined")

SessionState = Literal["upcoming", "ongoing", "past", "cancelled"]


def session_state(starts_at: datetime, minutes: int, status: str, now: datetime) -> SessionState:
    """Where a study session is in time. A cancelled session stays cancelled whatever the clock says."""
    if status == "cancelled":
        return "cancelled"
    if now < starts_at:
        return "upcoming"
    if now < starts_at + timedelta(minutes=minutes):
        return "ongoing"
    return "past"


def rsvp_counts(responses: Iterable[str]) -> dict[str, int]:
    """How many said going, maybe and declined (all three keys always present)."""
    counts = dict.fromkeys(RSVPS, 0)
    for response in responses:
        if response in counts:
            counts[response] += 1
    return counts


def excerpt(text: str, limit: int = 160) -> str:
    """The start of a note or post, on one line, for lists."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
