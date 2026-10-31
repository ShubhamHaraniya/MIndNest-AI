"""What a study group does together besides sharing files: invitations, shared notes, discussions
and study sessions.

Everything here belongs to one group and is visible only to its members (row-level security,
migration 0023). Members write; the author changes their own work; owners and admins can also
remove anything, pin notes and discussions, and lock a discussion. Invitations go to an email
address and are answered by whoever signs in with that address.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from mindnest_core.grouplogic import (
    MAX_GROUPS_PER_USER,
    MAX_MEMBERS,
    MAX_NOTES,
    MAX_PENDING_INVITES,
    MAX_POSTS_PER_THREAD,
    MAX_SESSION_MINUTES,
    MAX_SESSIONS,
    MAX_THREADS,
    MIN_SESSION_MINUTES,
    RSVPS,
    can_change,
    excerpt,
    is_admin,
    normalize_email,
    rsvp_counts,
    session_state,
)
from mindnest_core.plannerlogic import local_zone
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.groups import GroupOut, _admin_group, _group, _people

router = APIRouter(tags=["groups"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
PostBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Role = Literal["admin", "member"]
Response_ = Literal["going", "maybe", "declined"]


async def _names(session: AsyncSession, group_id: UUID, me: UUID) -> dict[UUID, str]:
    return {p.user_id: p.display_name for p in await _people(session, group_id, me)}


# ================================================================================ invitations


class InviteIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    role: Role = "member"


class InvitationOut(BaseModel):
    id: UUID
    email: str
    role: Role
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime


class MyInvitationOut(BaseModel):
    id: UUID
    group_id: UUID
    group_name: str
    group_description: str
    role: Role
    invited_by_name: str
    created_at: datetime
    expires_at: datetime


_INVITE_SQL = (
    "SELECT id, email, role, invited_by, created_at, expires_at FROM group_invitations "
    "WHERE status = 'pending' AND expires_at > now()"
)


def _invitation_out(row: Any, names: dict[UUID, str]) -> InvitationOut:
    return InvitationOut(
        id=row["id"], email=row["email"], role=row["role"], invited_by_name=names.get(row["invited_by"]),
        created_at=row["created_at"], expires_at=row["expires_at"],
    )


@router.get("/groups/{group_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(group_id: UUID, user: AuthUser, db: UserDbDep) -> list[InvitationOut]:
    async with db.session() as session:
        await _admin_group(session, group_id, user.id)
        rows = (
            (await session.execute(text(f"{_INVITE_SQL} AND group_id = :g ORDER BY created_at DESC"), {"g": group_id}))
            .mappings()
            .all()
        )
        names = await _names(session, group_id, user.id)
    return [_invitation_out(r, names) for r in rows]


@router.post("/groups/{group_id}/invitations", status_code=201, response_model=InvitationOut)
async def invite(group_id: UUID, body: InviteIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> InvitationOut:
    """Invite someone by email. They see the invitation when they sign in with that address."""
    await limiter.check(f"group:invite:{user.id}", 30, 3600)
    email = normalize_email(body.email)
    if email is None:
        raise AppError(422, "invalid_email", "That does not look like an email address.")
    if email == user.email.lower():
        raise AppError(409, "already_member", "You are already in this group.")
    async with db.session() as session:
        group = await _admin_group(session, group_id, user.id)
        if body.role == "admin" and group.role != "owner":
            raise AppError(403, "owner_only", "Only the group owner can invite an admin.")
        if (
            await session.execute(
                text("SELECT app_email_in_group(:g, :e)"), {"g": group_id, "e": email}
            )
        ).scalar_one():
            raise AppError(409, "already_member", "That person is already in this group.")
        # An invitation that ran out no longer stands in the way of a new one.
        await session.execute(
            text(
                "UPDATE group_invitations SET status = 'revoked', responded_at = now() WHERE group_id = :g "
                "AND lower(email) = :e AND status = 'pending' AND expires_at <= now()"
            ),
            {"g": group_id, "e": email},
        )
        pending = (
            await session.execute(
                text("SELECT count(*) FROM group_invitations WHERE group_id = :g AND status = 'pending' AND expires_at > now()"),
                {"g": group_id},
            )
        ).scalar_one()
        if pending >= MAX_PENDING_INVITES:
            raise AppError(409, "too_many_invitations", "This group has too many open invitations.")
        try:
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO group_invitations (group_id, invited_by, email, role) "
                            "VALUES (:g, :u, :e, :r) RETURNING id, email, role, invited_by, created_at, expires_at"
                        ),
                        {"g": group_id, "u": user.id, "e": email, "r": body.role},
                    )
                )
                .mappings()
                .one()
            )
        except IntegrityError:
            raise AppError(409, "already_invited", "That address already has an open invitation.") from None
        names = await _names(session, group_id, user.id)
    return _invitation_out(row, names)


@router.delete("/groups/{group_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(group_id: UUID, invitation_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        await _admin_group(session, group_id, user.id)
        result = await session.execute(
            text(
                "UPDATE group_invitations SET status = 'revoked', responded_at = now() "
                "WHERE id = :i AND group_id = :g AND status = 'pending'"
            ),
            {"i": invitation_id, "g": group_id},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Invitation not found.")
    return Response(status_code=204)


@router.get("/group-invitations", response_model=list[MyInvitationOut])
async def my_invitations(_user: AuthUser, db: UserDbDep) -> list[MyInvitationOut]:
    async with db.session() as session:
        rows = (await session.execute(text("SELECT * FROM app_my_invitations()"))).mappings().all()
    return [MyInvitationOut(**dict(r)) for r in rows]


@router.post("/group-invitations/{invitation_id}/accept", response_model=GroupOut)
async def accept_invitation(invitation_id: UUID, user: AuthUser, db: UserDbDep) -> GroupOut:
    async with db.session() as session:
        if int((await session.execute(text("SELECT count(*) FROM groups"))).scalar_one()) >= MAX_GROUPS_PER_USER:
            raise AppError(409, "too_many_groups", "You are in the most groups allowed.")
        group_id = (
            await session.execute(text("SELECT app_answer_invitation(:i, true)"), {"i": invitation_id})
        ).scalar_one()
        if group_id is None:
            raise AppError(404, "invitation_not_found", "That invitation is no longer open.")
        members = (
            await session.execute(text("SELECT count(*) FROM group_members WHERE group_id = :g"), {"g": group_id})
        ).scalar_one()
        if members > MAX_MEMBERS:
            await session.execute(
                text("DELETE FROM group_members WHERE group_id = :g AND user_id = :u"), {"g": group_id, "u": user.id}
            )
            raise AppError(409, "group_full", "That group is full.")
        return await _group(session, group_id, user.id)


@router.post("/group-invitations/{invitation_id}/decline", status_code=204)
async def decline_invitation(invitation_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        group_id = (
            await session.execute(text("SELECT app_answer_invitation(:i, false)"), {"i": invitation_id})
        ).scalar_one()
        if group_id is None:
            raise AppError(404, "invitation_not_found", "That invitation is no longer open.")
    return Response(status_code=204)


# ================================================================================ notes


class NoteIn(BaseModel):
    title: Title
    body: NoteBody = ""


class NotePatch(BaseModel):
    title: Title | None = None
    body: NoteBody | None = None
    pinned: bool | None = None


class NoteSummary(BaseModel):
    id: UUID
    title: str
    excerpt: str
    pinned: bool
    author_id: UUID
    author_name: str | None  # None: the author has left the group
    mine: bool
    can_change: bool
    created_at: datetime
    updated_at: datetime


class NoteOut(NoteSummary):
    body: str


_NOTE_SQL = "SELECT id, title, body, pinned, author_id, created_at, updated_at FROM group_notes"


def _note_out(row: Any, names: dict[UUID, str], me: UUID, role: str) -> NoteOut:
    return NoteOut(
        id=row["id"], title=row["title"], body=row["body"], excerpt=excerpt(row["body"]), pinned=row["pinned"],
        author_id=row["author_id"], author_name=names.get(row["author_id"]), mine=row["author_id"] == me,
        can_change=can_change(role, row["author_id"] == me), created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _note_row(session: AsyncSession, group_id: UUID, note_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_NOTE_SQL} WHERE id = :i AND group_id = :g"), {"i": note_id, "g": group_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Note not found.")
    return row


@router.get("/groups/{group_id}/notes", response_model=list[NoteSummary])
async def list_notes(group_id: UUID, user: AuthUser, db: UserDbDep) -> list[NoteSummary]:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        rows = (
            (
                await session.execute(
                    text(f"{_NOTE_SQL} WHERE group_id = :g ORDER BY pinned DESC, updated_at DESC LIMIT {MAX_NOTES}"),
                    {"g": group_id},
                )
            )
            .mappings()
            .all()
        )
        names = await _names(session, group_id, user.id)
    return [NoteSummary(**_note_out(r, names, user.id, group.role).model_dump(exclude={"body"})) for r in rows]


@router.post("/groups/{group_id}/notes", status_code=201, response_model=NoteOut)
async def create_note(group_id: UUID, body: NoteIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> NoteOut:
    await limiter.check(f"group:note:{user.id}", 60, 3600)
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        count = (
            await session.execute(text("SELECT count(*) FROM group_notes WHERE group_id = :g"), {"g": group_id})
        ).scalar_one()
        if count >= MAX_NOTES:
            raise AppError(409, "group_notes_full", "This group has the most notes allowed.")
        note_id = (
            await session.execute(
                text("INSERT INTO group_notes (group_id, author_id, title, body) VALUES (:g, :u, :t, :b) RETURNING id"),
                {"g": group_id, "u": user.id, "t": body.title, "b": body.body},
            )
        ).scalar_one()
        return _note_out(await _note_row(session, group_id, note_id), await _names(session, group_id, user.id), user.id, group.role)


@router.get("/groups/{group_id}/notes/{note_id}", response_model=NoteOut)
async def get_note(group_id: UUID, note_id: UUID, user: AuthUser, db: UserDbDep) -> NoteOut:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _note_row(session, group_id, note_id)
        names = await _names(session, group_id, user.id)
    return _note_out(row, names, user.id, group.role)


@router.patch("/groups/{group_id}/notes/{note_id}", response_model=NoteOut)
async def update_note(group_id: UUID, note_id: UUID, body: NotePatch, user: AuthUser, db: UserDbDep) -> NoteOut:
    sent = body.model_fields_set
    for name in ("title", "body", "pinned"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _note_row(session, group_id, note_id)
        mine = row["author_id"] == user.id
        if ({"title", "body"} & sent) and not mine:
            raise AppError(403, "not_author", "Only the author can change what a note says.")
        if "pinned" in sent and not is_admin(group.role):
            raise AppError(403, "admin_only", "Only a group owner or admin can pin a note.")
        changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
        if changes:
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            touched = ", updated_at = now()" if ({"title", "body"} & sent) else ""
            await session.execute(
                text(f"UPDATE group_notes SET {sets}{touched} WHERE id = :id"), {**changes, "id": note_id}
            )
        row = await _note_row(session, group_id, note_id)
        names = await _names(session, group_id, user.id)
    return _note_out(row, names, user.id, group.role)


@router.delete("/groups/{group_id}/notes/{note_id}", status_code=204)
async def delete_note(group_id: UUID, note_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _note_row(session, group_id, note_id)
        if not can_change(group.role, row["author_id"] == user.id):
            raise AppError(403, "not_author", "Only the author or a group admin can delete a note.")
        await session.execute(text("DELETE FROM group_notes WHERE id = :i"), {"i": note_id})
    return Response(status_code=204)


# ================================================================================ discussions


class ThreadIn(BaseModel):
    title: Title
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""


class ThreadPatch(BaseModel):
    title: Title | None = None
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    pinned: bool | None = None
    locked: bool | None = None


class PostIn(BaseModel):
    body: PostBody


class PostOut(BaseModel):
    id: UUID
    body: str
    author_id: UUID
    author_name: str | None
    mine: bool
    can_edit: bool
    can_delete: bool
    created_at: datetime
    edited_at: datetime | None


class ThreadSummary(BaseModel):
    id: UUID
    title: str
    excerpt: str
    pinned: bool
    locked: bool
    author_id: UUID
    author_name: str | None
    mine: bool
    reply_count: int
    created_at: datetime
    last_activity_at: datetime


class ThreadOut(ThreadSummary):
    body: str
    edited_at: datetime | None
    can_edit: bool
    can_delete: bool
    can_moderate: bool
    posts: list[PostOut]


_THREAD_SQL = """
  SELECT t.id, t.title, t.body, t.pinned, t.locked, t.author_id, t.created_at, t.edited_at, t.last_activity_at,
         (SELECT count(*) FROM group_posts p WHERE p.thread_id = t.id) AS reply_count
  FROM group_threads t
"""


def _thread_summary(row: Any, names: dict[UUID, str], me: UUID) -> ThreadSummary:
    return ThreadSummary(
        id=row["id"], title=row["title"], excerpt=excerpt(row["body"]), pinned=row["pinned"], locked=row["locked"],
        author_id=row["author_id"], author_name=names.get(row["author_id"]), mine=row["author_id"] == me,
        reply_count=int(row["reply_count"]), created_at=row["created_at"], last_activity_at=row["last_activity_at"],
    )


def _post_out(row: Any, names: dict[UUID, str], me: UUID, role: str) -> PostOut:
    mine = row["author_id"] == me
    return PostOut(
        id=row["id"], body=row["body"], author_id=row["author_id"], author_name=names.get(row["author_id"]),
        mine=mine, can_edit=mine, can_delete=can_change(role, mine), created_at=row["created_at"],
        edited_at=row["edited_at"],
    )


async def _thread_row(session: AsyncSession, group_id: UUID, thread_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_THREAD_SQL} WHERE t.id = :i AND t.group_id = :g"), {"i": thread_id, "g": group_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Discussion not found.")
    return row


async def _thread_out(session: AsyncSession, group_id: UUID, thread_id: UUID, me: UUID, role: str) -> ThreadOut:
    row = await _thread_row(session, group_id, thread_id)
    posts = (
        (
            await session.execute(
                text(
                    "SELECT id, body, author_id, created_at, edited_at FROM group_posts "
                    "WHERE thread_id = :t ORDER BY created_at LIMIT 500"
                ),
                {"t": thread_id},
            )
        )
        .mappings()
        .all()
    )
    names = await _names(session, group_id, me)
    mine = row["author_id"] == me
    return ThreadOut(
        **_thread_summary(row, names, me).model_dump(), body=row["body"], edited_at=row["edited_at"],
        can_edit=mine, can_delete=can_change(role, mine), can_moderate=is_admin(role),
        posts=[_post_out(p, names, me, role) for p in posts],
    )


@router.get("/groups/{group_id}/threads", response_model=list[ThreadSummary])
async def list_threads(group_id: UUID, user: AuthUser, db: UserDbDep) -> list[ThreadSummary]:
    async with db.session() as session:
        await _group(session, group_id, user.id)
        rows = (
            (
                await session.execute(
                    text(f"{_THREAD_SQL} WHERE t.group_id = :g ORDER BY t.pinned DESC, t.last_activity_at DESC LIMIT {MAX_THREADS}"),
                    {"g": group_id},
                )
            )
            .mappings()
            .all()
        )
        names = await _names(session, group_id, user.id)
    return [_thread_summary(r, names, user.id) for r in rows]


@router.post("/groups/{group_id}/threads", status_code=201, response_model=ThreadOut)
async def create_thread(group_id: UUID, body: ThreadIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> ThreadOut:
    await limiter.check(f"group:thread:{user.id}", 40, 3600)
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        count = (
            await session.execute(text("SELECT count(*) FROM group_threads WHERE group_id = :g"), {"g": group_id})
        ).scalar_one()
        if count >= MAX_THREADS:
            raise AppError(409, "group_threads_full", "This group has the most discussions allowed.")
        thread_id = (
            await session.execute(
                text("INSERT INTO group_threads (group_id, author_id, title, body) VALUES (:g, :u, :t, :b) RETURNING id"),
                {"g": group_id, "u": user.id, "t": body.title, "b": body.body},
            )
        ).scalar_one()
        return await _thread_out(session, group_id, thread_id, user.id, group.role)


@router.get("/groups/{group_id}/threads/{thread_id}", response_model=ThreadOut)
async def get_thread(group_id: UUID, thread_id: UUID, user: AuthUser, db: UserDbDep) -> ThreadOut:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        return await _thread_out(session, group_id, thread_id, user.id, group.role)


@router.patch("/groups/{group_id}/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(group_id: UUID, thread_id: UUID, body: ThreadPatch, user: AuthUser, db: UserDbDep) -> ThreadOut:
    sent = body.model_fields_set
    for name in ("title", "body", "pinned", "locked"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _thread_row(session, group_id, thread_id)
        if ({"title", "body"} & sent) and row["author_id"] != user.id:
            raise AppError(403, "not_author", "Only the author can change what a discussion says.")
        if ({"pinned", "locked"} & sent) and not is_admin(group.role):
            raise AppError(403, "admin_only", "Only a group owner or admin can pin or lock a discussion.")
        changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
        if changes:
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            edited = ", edited_at = now()" if ({"title", "body"} & sent) else ""
            await session.execute(
                text(f"UPDATE group_threads SET {sets}{edited} WHERE id = :id"), {**changes, "id": thread_id}
            )
        return await _thread_out(session, group_id, thread_id, user.id, group.role)


@router.delete("/groups/{group_id}/threads/{thread_id}", status_code=204)
async def delete_thread(group_id: UUID, thread_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _thread_row(session, group_id, thread_id)
        if not can_change(group.role, row["author_id"] == user.id):
            raise AppError(403, "not_author", "Only the author or a group admin can delete a discussion.")
        await session.execute(text("DELETE FROM group_threads WHERE id = :i"), {"i": thread_id})
    return Response(status_code=204)


@router.post("/groups/{group_id}/threads/{thread_id}/posts", status_code=201, response_model=PostOut)
async def reply(
    group_id: UUID, thread_id: UUID, body: PostIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> PostOut:
    await limiter.check(f"group:post:{user.id}", 120, 3600)
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        thread = await _thread_row(session, group_id, thread_id)
        if thread["locked"] and not is_admin(group.role):
            raise AppError(409, "thread_locked", "This discussion is locked.")
        if int(thread["reply_count"]) >= MAX_POSTS_PER_THREAD:
            raise AppError(409, "thread_full", "This discussion has the most replies allowed.")
        post = (
            (
                await session.execute(
                    text(
                        "INSERT INTO group_posts (thread_id, group_id, author_id, body) VALUES (:t, :g, :u, :b) "
                        "RETURNING id, body, author_id, created_at, edited_at"
                    ),
                    {"t": thread_id, "g": group_id, "u": user.id, "b": body.body},
                )
            )
            .mappings()
            .one()
        )
        await session.execute(text("UPDATE group_threads SET last_activity_at = now() WHERE id = :i"), {"i": thread_id})
        names = await _names(session, group_id, user.id)
    return _post_out(post, names, user.id, group.role)


async def _post_row(session: AsyncSession, group_id: UUID, thread_id: UUID, post_id: UUID) -> Any:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, body, author_id, created_at, edited_at FROM group_posts "
                    "WHERE id = :p AND thread_id = :t AND group_id = :g"
                ),
                {"p": post_id, "t": thread_id, "g": group_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Reply not found.")
    return row


@router.patch("/groups/{group_id}/threads/{thread_id}/posts/{post_id}", response_model=PostOut)
async def edit_post(
    group_id: UUID, thread_id: UUID, post_id: UUID, body: PostIn, user: AuthUser, db: UserDbDep
) -> PostOut:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _post_row(session, group_id, thread_id, post_id)
        if row["author_id"] != user.id:
            raise AppError(403, "not_author", "Only the author can change a reply.")
        await session.execute(
            text("UPDATE group_posts SET body = :b, edited_at = now() WHERE id = :i"), {"b": body.body, "i": post_id}
        )
        row = await _post_row(session, group_id, thread_id, post_id)
        names = await _names(session, group_id, user.id)
    return _post_out(row, names, user.id, group.role)


@router.delete("/groups/{group_id}/threads/{thread_id}/posts/{post_id}", status_code=204)
async def delete_post(group_id: UUID, thread_id: UUID, post_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _post_row(session, group_id, thread_id, post_id)
        if not can_change(group.role, row["author_id"] == user.id):
            raise AppError(403, "not_author", "Only the author or a group admin can delete a reply.")
        await session.execute(text("DELETE FROM group_posts WHERE id = :i"), {"i": post_id})
    return Response(status_code=204)


# ================================================================================ study sessions


class SessionIn(BaseModel):
    title: Title
    description: Short = ""
    starts_at: datetime
    minutes: int = Field(default=60, ge=MIN_SESSION_MINUTES, le=MAX_SESSION_MINUTES)
    location: Place = ""


class SessionPatch(BaseModel):
    title: Title | None = None
    description: Short | None = None
    starts_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=MIN_SESSION_MINUTES, le=MAX_SESSION_MINUTES)
    location: Place | None = None
    status: Literal["scheduled", "cancelled"] | None = None


class RsvpIn(BaseModel):
    response: Response_


class AttendeeOut(BaseModel):
    user_id: UUID
    name: str
    response: Response_


class SessionOut(BaseModel):
    id: UUID
    title: str
    description: str
    starts_at: datetime
    minutes: int
    location: str
    status: Literal["scheduled", "cancelled"]
    state: Literal["upcoming", "ongoing", "past", "cancelled"]
    created_by: UUID
    created_by_name: str | None
    mine: bool
    can_change: bool
    going: int
    maybe: int
    declined: int
    my_response: Response_ | None
    attendees: list[AttendeeOut]


class CalendarAdded(BaseModel):
    event_id: UUID
    day: date
    start_time: str
    already: bool


_SESSION_SQL = """
  SELECT id, title, description, starts_at, minutes, location, status, created_by
  FROM group_sessions
"""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AppError(422, "validation_error", "Give the start time with its time zone.")
    return value.astimezone(UTC)


async def _session_outs(
    session: AsyncSession, group_id: UUID, rows: list[Any], me: UUID, role: str
) -> list[SessionOut]:
    names = await _names(session, group_id, me)
    ids = [r["id"] for r in rows]
    rsvps: dict[UUID, list[Any]] = {i: [] for i in ids}
    if ids:
        for r in (
            await session.execute(
                text(
                    "SELECT session_id, user_id, response FROM group_session_rsvps "
                    "WHERE session_id = ANY(:ids) ORDER BY updated_at"
                ),
                {"ids": ids},
            )
        ).mappings():
            rsvps[r["session_id"]].append(r)
    now = datetime.now(UTC)
    out: list[SessionOut] = []
    for r in rows:
        answers = rsvps[r["id"]]
        counts = rsvp_counts([a["response"] for a in answers])
        mine = r["created_by"] == me
        out.append(
            SessionOut(
                id=r["id"], title=r["title"], description=r["description"], starts_at=r["starts_at"],
                minutes=r["minutes"], location=r["location"], status=r["status"],
                state=session_state(r["starts_at"], r["minutes"], r["status"], now),
                created_by=r["created_by"], created_by_name=names.get(r["created_by"]), mine=mine,
                can_change=can_change(role, mine), going=counts["going"], maybe=counts["maybe"],
                declined=counts["declined"],
                my_response=next((a["response"] for a in answers if a["user_id"] == me), None),
                attendees=[
                    AttendeeOut(user_id=a["user_id"], name=names[a["user_id"]], response=a["response"])
                    for a in answers
                    if a["user_id"] in names
                ],
            )
        )
    return out


async def _session_row(session: AsyncSession, group_id: UUID, session_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_SESSION_SQL} WHERE id = :i AND group_id = :g"), {"i": session_id, "g": group_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Study session not found.")
    return row


async def _one_session(session: AsyncSession, group_id: UUID, session_id: UUID, me: UUID, role: str) -> SessionOut:
    row = await _session_row(session, group_id, session_id)
    return (await _session_outs(session, group_id, [row], me, role))[0]


@router.get("/groups/{group_id}/sessions", response_model=list[SessionOut])
async def list_sessions(group_id: UUID, user: AuthUser, db: UserDbDep) -> list[SessionOut]:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        rows = (
            (
                await session.execute(
                    text(f"{_SESSION_SQL} WHERE group_id = :g ORDER BY starts_at LIMIT {MAX_SESSIONS}"), {"g": group_id}
                )
            )
            .mappings()
            .all()
        )
        return await _session_outs(session, group_id, list(rows), user.id, group.role)


@router.post("/groups/{group_id}/sessions", status_code=201, response_model=SessionOut)
async def create_session(group_id: UUID, body: SessionIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> SessionOut:
    await limiter.check(f"group:session:{user.id}", 40, 3600)
    starts = _aware(body.starts_at)
    if starts < datetime.now(UTC) - timedelta(minutes=5):
        raise AppError(422, "session_in_past", "Choose a time that has not passed yet.")
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        count = (
            await session.execute(text("SELECT count(*) FROM group_sessions WHERE group_id = :g"), {"g": group_id})
        ).scalar_one()
        if count >= MAX_SESSIONS:
            raise AppError(409, "group_sessions_full", "This group has the most study sessions allowed.")
        twin = (
            await session.execute(
                text("SELECT 1 FROM group_sessions WHERE group_id = :g AND lower(title) = lower(:t) AND starts_at = :s"),
                {"g": group_id, "t": body.title, "s": starts},
            )
        ).first()
        if twin is not None:
            raise AppError(409, "session_duplicate", "This group already has a session with that name at that time.")
        session_id = (
            await session.execute(
                text(
                    "INSERT INTO group_sessions (group_id, created_by, title, description, starts_at, minutes, location) "
                    "VALUES (:g, :u, :t, :d, :s, :m, :l) RETURNING id"
                ),
                {"g": group_id, "u": user.id, "t": body.title, "d": body.description, "s": starts, "m": body.minutes, "l": body.location},
            )
        ).scalar_one()
        # Whoever sets it up is coming.
        await session.execute(
            text(
                "INSERT INTO group_session_rsvps (session_id, group_id, user_id, response) VALUES (:i, :g, :u, 'going')"
            ),
            {"i": session_id, "g": group_id, "u": user.id},
        )
        return await _one_session(session, group_id, session_id, user.id, group.role)


@router.get("/groups/{group_id}/sessions/{session_id}", response_model=SessionOut)
async def get_session(group_id: UUID, session_id: UUID, user: AuthUser, db: UserDbDep) -> SessionOut:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        return await _one_session(session, group_id, session_id, user.id, group.role)


@router.patch("/groups/{group_id}/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    group_id: UUID, session_id: UUID, body: SessionPatch, user: AuthUser, db: UserDbDep
) -> SessionOut:
    sent = body.model_fields_set
    for name in ("title", "description", "starts_at", "minutes", "location", "status"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
    if "starts_at" in changes:
        changes["starts_at"] = _aware(changes["starts_at"])
        if changes["starts_at"] < datetime.now(UTC) - timedelta(minutes=5):
            raise AppError(422, "session_in_past", "Choose a time that has not passed yet.")
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _session_row(session, group_id, session_id)
        if not can_change(group.role, row["created_by"] == user.id):
            raise AppError(403, "not_author", "Only the person who set it up or a group admin can change a session.")
        if changes:
            title = changes.get("title", row["title"])
            starts = changes.get("starts_at", row["starts_at"])
            twin = (
                await session.execute(
                    text(
                        "SELECT 1 FROM group_sessions WHERE group_id = :g AND lower(title) = lower(:t) "
                        "AND starts_at = :s AND id <> :i"
                    ),
                    {"g": group_id, "t": title, "s": starts, "i": session_id},
                )
            ).first()
            if twin is not None:
                raise AppError(409, "session_duplicate", "This group already has a session with that name at that time.")
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            await session.execute(
                text(f"UPDATE group_sessions SET {sets}, updated_at = now() WHERE id = :id"), {**changes, "id": session_id}
            )
        return await _one_session(session, group_id, session_id, user.id, group.role)


@router.delete("/groups/{group_id}/sessions/{session_id}", status_code=204)
async def delete_session(group_id: UUID, session_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _session_row(session, group_id, session_id)
        if not can_change(group.role, row["created_by"] == user.id):
            raise AppError(403, "not_author", "Only the person who set it up or a group admin can delete a session.")
        await session.execute(text("DELETE FROM group_sessions WHERE id = :i"), {"i": session_id})
    return Response(status_code=204)


@router.put("/groups/{group_id}/sessions/{session_id}/rsvp", response_model=SessionOut)
async def rsvp(group_id: UUID, session_id: UUID, body: RsvpIn, user: AuthUser, db: UserDbDep) -> SessionOut:
    if body.response not in RSVPS:  # pragma: no cover (the type already says so)
        raise AppError(422, "validation_error", "Choose going, maybe or declined.")
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _session_row(session, group_id, session_id)
        if session_state(row["starts_at"], row["minutes"], row["status"], datetime.now(UTC)) in ("past", "cancelled"):
            raise AppError(409, "session_closed", "This session is over or cancelled.")
        await session.execute(
            text(
                "INSERT INTO group_session_rsvps (session_id, group_id, user_id, response) VALUES (:i, :g, :u, :r) "
                "ON CONFLICT (session_id, user_id) DO UPDATE SET response = :r, updated_at = now()"
            ),
            {"i": session_id, "g": group_id, "u": user.id, "r": body.response},
        )
        return await _one_session(session, group_id, session_id, user.id, group.role)


@router.delete("/groups/{group_id}/sessions/{session_id}/rsvp", response_model=SessionOut)
async def clear_rsvp(group_id: UUID, session_id: UUID, user: AuthUser, db: UserDbDep) -> SessionOut:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        await _session_row(session, group_id, session_id)
        await session.execute(
            text("DELETE FROM group_session_rsvps WHERE session_id = :i AND user_id = :u"),
            {"i": session_id, "u": user.id},
        )
        return await _one_session(session, group_id, session_id, user.id, group.role)


@router.post("/groups/{group_id}/sessions/{session_id}/calendar", response_model=CalendarAdded)
async def add_to_my_calendar(group_id: UUID, session_id: UUID, user: AuthUser, db: UserDbDep) -> CalendarAdded:
    """Put this session on the student's own calendar, once: asking again returns the same event."""
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        row = await _session_row(session, group_id, session_id)
        local = row["starts_at"].astimezone(local_zone(user.timezone))
        title = f"{group.name}: {row['title']}"[:200]
        notes = "\n".join(part for part in (row["description"], row["location"]) if part)[:1000]
        key = f"gs-{session_id}"
        made = (
            await session.execute(
                text(
                    "INSERT INTO calendar_events (user_id, title, notes, day, start_time, minutes, request_key) "
                    "VALUES (:u, :t, :n, :d, :st, :m, :k) ON CONFLICT DO NOTHING RETURNING id"
                ),
                {
                    "u": user.id, "t": title, "n": notes, "d": local.date(), "st": local.strftime("%H:%M"),
                    "m": row["minutes"], "k": key,
                },
            )
        ).scalar_one_or_none()
        if made is not None:
            return CalendarAdded(event_id=made, day=local.date(), start_time=local.strftime("%H:%M"), already=False)
        existing = (
            (
                await session.execute(
                    text("SELECT id, day, start_time FROM calendar_events WHERE request_key = :k"), {"k": key}
                )
            )
            .mappings()
            .first()
        )
        if existing is None:  # the same title already sits at that time on the calendar
            raise AppError(409, "event_duplicate", "You already have an event with this name at this time.")
        return CalendarAdded(
            event_id=existing["id"], day=existing["day"], start_time=existing["start_time"], already=True
        )
