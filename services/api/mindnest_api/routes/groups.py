"""Study groups: a private library shared only among a college class or friends.

A student joins with a code the group owner hands out. Files are copied into the group (so the
original can change or go away), and a member can copy one into their own subject, where it goes
through the usual ingestion like any upload. Row-level security (migration 0011) is what keeps a
group's rows from anyone who is not a member; the checks here give clear errors on top of that.
"""

import asyncio
import io
import logging
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from mindnest_core.filetypes import ALLOWED_TYPES, extension_of, looks_like
from mindnest_core.grouplogic import (
    HIDE_AT_REPORTS,
    MAX_GROUPS_PER_USER,
    MAX_ITEMS,
    MAX_MEMBERS,
    can_remove_member,
    can_set_role,
    display_code,
    is_admin,
    new_join_code,
    normalize_code,
)
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, StorageDep, UserDbDep, client_ip
from mindnest_api.errors import AppError

router = APIRouter(tags=["groups"])
log = logging.getLogger("mindnest.groups")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Kind = Literal["material", "past_paper", "note", "assignment"]
Reason = Literal["copyright", "inappropriate", "wrong_content", "other"]
Rights = Literal["own_work", "permitted", "open_licence"]
Credit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


# ------------------------------------------------------------------------------ schemas


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str
    role: Literal["owner", "admin", "member"]
    member_count: int
    item_count: int
    # Only the owner sees (and hands out) the code.
    join_code: str | None
    created_at: datetime


class PersonOut(BaseModel):
    user_id: UUID
    display_name: str
    role: Literal["owner", "admin", "member"]
    joined_at: datetime
    is_me: bool


class GroupDetail(GroupOut):
    members: list[PersonOut]


class GroupIn(BaseModel):
    name: Name
    description: Description = ""


class GroupPatch(BaseModel):
    name: Name | None = None
    description: Description | None = None


class RoleIn(BaseModel):
    role: Literal["admin", "member"]


class JoinIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ItemOut(BaseModel):
    id: UUID
    filename: str
    kind: Kind
    mime_type: str | None
    size_bytes: int | None
    note: str
    status: Literal["active", "hidden"]
    shared_by_name: str
    mine: bool
    # Where it came from: the course it was filed under, who wrote it, which institution, and why
    # the sharer may pass it on.
    course_name: str | None = None
    author: str = ""
    institution: str = ""
    rights: Rights = "own_work"
    # What this member may do with it.
    can_remove: bool = False
    can_report: bool = False
    reported_by_me: bool
    # How many members reported it. Only the group owner is told.
    reports: int | None
    created_at: datetime


class ShareIn(BaseModel):
    material_id: UUID
    note: Note = ""
    author: Credit = ""
    institution: Credit = ""
    rights: Rights = "own_work"
    # The student confirms they may share this file (their own notes, or material they are allowed to pass on).
    confirm_rights: bool


class AddIn(BaseModel):
    subject_id: UUID


class AddedOut(BaseModel):
    material_id: UUID
    subject_id: UUID


class ReportIn(BaseModel):
    reason: Reason
    note: Note = ""


class ReportOut(BaseModel):
    hidden: bool


class ShareableOut(BaseModel):
    id: UUID
    filename: str
    kind: Kind
    size_bytes: int | None
    subject_name: str


# ------------------------------------------------------------------------------ helpers

_GROUP_SQL = """
  SELECT g.id, g.name, g.description, g.created_at,
         (SELECT m.role FROM group_members m WHERE m.group_id = g.id AND m.user_id = :me) AS role,
         (SELECT count(*) FROM group_members m WHERE m.group_id = g.id) AS member_count,
         (SELECT count(*) FROM shared_items s WHERE s.group_id = g.id AND s.status = 'active') AS item_count,
         CASE WHEN EXISTS (SELECT 1 FROM group_members m
                           WHERE m.group_id = g.id AND m.user_id = :me AND m.role = 'owner')
              THEN g.join_code END AS join_code
  FROM groups g
"""


def _group_out(row: dict) -> GroupOut:  # type: ignore[type-arg]
    return GroupOut(
        id=row["id"], name=row["name"], description=row["description"], role=row["role"],
        member_count=row["member_count"], item_count=row["item_count"],
        join_code=display_code(row["join_code"]) if row["join_code"] else None,
        created_at=row["created_at"],
    )


async def _group(session: AsyncSession, group_id: UUID, me: UUID) -> GroupOut:
    row = (
        (await session.execute(text(f"{_GROUP_SQL} WHERE g.id = :id"), {"id": group_id, "me": me}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Group not found.")
    return _group_out(dict(row))


async def _owner_group(session: AsyncSession, group_id: UUID, me: UUID) -> GroupOut:
    group = await _group(session, group_id, me)
    if group.role != "owner":
        raise AppError(403, "owner_only", "Only the group owner can do that.")
    return group


async def _admin_group(session: AsyncSession, group_id: UUID, me: UUID) -> GroupOut:
    group = await _group(session, group_id, me)
    if not is_admin(group.role):
        raise AppError(403, "admin_only", "Only a group owner or admin can do that.")
    return group


async def _people(session: AsyncSession, group_id: UUID, me: UUID) -> list[PersonOut]:
    rows = (
        (await session.execute(text("SELECT * FROM app_group_people(:g)"), {"g": group_id}))
        .mappings()
        .all()
    )
    return [
        PersonOut(
            user_id=r["user_id"], display_name=r["display_name"], role=r["role"],
            joined_at=r["joined_at"], is_me=r["user_id"] == me,
        )
        for r in rows
    ]


async def _forget_files(storage: StorageDep, keys: list[str]) -> None:
    for key in keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            log.warning("could not delete stored file %s", key, exc_info=True)


def _disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename) or "file"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# ------------------------------------------------------------------------------ groups


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(user: AuthUser, db: UserDbDep) -> list[GroupOut]:
    async with db.session() as session:
        rows = (
            (await session.execute(text(f"{_GROUP_SQL} ORDER BY g.created_at DESC"), {"me": user.id}))
            .mappings()
            .all()
        )
    return [_group_out(dict(r)) for r in rows]


async def _my_group_count(session: AsyncSession) -> int:
    return int((await session.execute(text("SELECT count(*) FROM groups"))).scalar_one())


@router.post("/groups", status_code=201, response_model=GroupOut)
async def create_group(body: GroupIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> GroupOut:
    await limiter.check(f"group:create:{user.id}", 10, 3600)
    async with db.session() as session:
        if await _my_group_count(session) >= MAX_GROUPS_PER_USER:
            raise AppError(409, "too_many_groups", "You are in the most groups allowed.")
    for _ in range(5):
        try:
            async with db.session() as session:
                gid = (
                    await session.execute(
                        text("SELECT app_create_group(:n, :d, :c)"),
                        {"n": body.name, "d": body.description, "c": new_join_code()},
                    )
                ).scalar_one()
                return await _group(session, gid, user.id)
        except (IntegrityError, DBAPIError) as exc:
            if "groups_join_code_idx" not in str(exc):
                raise
    raise AppError(503, "try_again", "Could not make a group just now. Please try again.")


@router.post("/groups/join", response_model=GroupOut)
async def join_group(
    body: JoinIn, request: Request, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> GroupOut:
    # Guessing codes is the only attack here, so both the student and the address are limited.
    await limiter.check(f"group:join:{user.id}", 10, 900)
    await limiter.check(f"group:join:ip:{client_ip(request)}", 40, 3600)
    code = normalize_code(body.code)
    if code is None:
        raise AppError(404, "group_not_found", "That code does not match a group.")
    async with db.session() as session:
        if await _my_group_count(session) >= MAX_GROUPS_PER_USER:
            raise AppError(409, "too_many_groups", "You are in the most groups allowed.")
    full = False
    async with db.session() as session:
        before = {r[0] for r in (await session.execute(text("SELECT group_id FROM group_members"))).all()}
        gid = (await session.execute(text("SELECT app_join_group(:c)"), {"c": code})).scalar_one()
        if gid is None:
            raise AppError(404, "group_not_found", "That code does not match a group.")
        members = (
            await session.execute(text("SELECT count(*) FROM group_members WHERE group_id = :g"), {"g": gid})
        ).scalar_one()
        if gid not in before and members > MAX_MEMBERS:
            await session.execute(
                text("DELETE FROM group_members WHERE group_id = :g AND user_id = :u"),
                {"g": gid, "u": user.id},
            )
            full = True
        else:
            group = await _group(session, gid, user.id)
    if full:
        raise AppError(409, "group_full", "That group is full.")
    return group


@router.get("/groups/{group_id}", response_model=GroupDetail)
async def get_group(group_id: UUID, user: AuthUser, db: UserDbDep) -> GroupDetail:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        members = await _people(session, group_id, user.id)
    return GroupDetail(**group.model_dump(), members=members)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def update_group(group_id: UUID, body: GroupPatch, user: AuthUser, db: UserDbDep) -> GroupOut:
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise AppError(422, "validation_error", "A group needs a name.")
    async with db.session() as session:
        await _owner_group(session, group_id, user.id)
        if changes:
            sets = ", ".join(f"{column} = :{column}" for column in changes)
            await session.execute(text(f"UPDATE groups SET {sets} WHERE id = :id"), {**changes, "id": group_id})
        return await _group(session, group_id, user.id)


@router.post("/groups/{group_id}/code", response_model=GroupOut)
async def new_code(group_id: UUID, user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> GroupOut:
    """Retire the old code and make a new one (for example after it was shared too widely)."""
    await limiter.check(f"group:code:{user.id}", 20, 3600)
    for _ in range(5):
        try:
            async with db.session() as session:
                await _owner_group(session, group_id, user.id)
                await session.execute(
                    text("UPDATE groups SET join_code = :c WHERE id = :id"),
                    {"c": new_join_code(), "id": group_id},
                )
                return await _group(session, group_id, user.id)
        except IntegrityError:
            continue
    raise AppError(503, "try_again", "Could not make a new code just now. Please try again.")


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: UUID, user: AuthUser, db: UserDbDep, storage: StorageDep) -> Response:
    async with db.session() as session:
        await _owner_group(session, group_id, user.id)
        keys = [
            r[0]
            for r in (
                await session.execute(
                    text("SELECT storage_key FROM shared_items WHERE group_id = :g"), {"g": group_id}
                )
            ).all()
        ]
        await session.execute(text("DELETE FROM groups WHERE id = :id"), {"id": group_id})
    await _forget_files(storage, keys)
    return Response(status_code=204)


async def _leave(session: AsyncSession, group_id: UUID, member_id: UUID) -> list[str]:
    """Remove a member and everything they shared here. Returns the stored files to delete."""
    keys = [
        r[0]
        for r in (
            await session.execute(
                text("DELETE FROM shared_items WHERE group_id = :g AND shared_by = :u RETURNING storage_key"),
                {"g": group_id, "u": member_id},
            )
        ).all()
    ]
    await session.execute(
        text("DELETE FROM group_members WHERE group_id = :g AND user_id = :u"), {"g": group_id, "u": member_id}
    )
    return keys


@router.post("/groups/{group_id}/leave", status_code=204)
async def leave_group(group_id: UUID, user: AuthUser, db: UserDbDep, storage: StorageDep) -> Response:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        if group.role == "owner":
            raise AppError(409, "owner_cannot_leave", "The owner can delete the group instead of leaving it.")
        keys = await _leave(session, group_id, user.id)
    await _forget_files(storage, keys)
    return Response(status_code=204)


@router.delete("/groups/{group_id}/members/{member_id}", status_code=204)
async def remove_member(
    group_id: UUID, member_id: UUID, user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    """An owner removes admins and members; an admin removes members. Their files go with them."""
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        if member_id == user.id:
            raise AppError(409, "owner_cannot_leave", "Use Leave to leave a group; the owner can delete it instead.")
        target = next((p for p in await _people(session, group_id, user.id) if p.user_id == member_id), None)
        if target is None:
            raise AppError(404, "not_found", "Member not found.")
        if not can_remove_member(group.role, target.role):
            raise AppError(403, "not_allowed", "You cannot remove this member.")
        keys = await _leave(session, group_id, member_id)
    await _forget_files(storage, keys)
    return Response(status_code=204)


@router.patch("/groups/{group_id}/members/{member_id}", response_model=PersonOut)
async def set_member_role(group_id: UUID, member_id: UUID, body: RoleIn, user: AuthUser, db: UserDbDep) -> PersonOut:
    """The owner makes a member an admin, or an admin an ordinary member again."""
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        target = next((p for p in await _people(session, group_id, user.id) if p.user_id == member_id), None)
        if target is None:
            raise AppError(404, "not_found", "Member not found.")
        if not can_set_role(group.role, target.role, body.role):
            raise AppError(403, "owner_only", "Only the group owner can change roles, and not the owner's own.")
        await session.execute(
            text("SELECT app_set_member_role(:g, :u, :r)"), {"g": group_id, "u": member_id, "r": body.role}
        )
        changed = next(p for p in await _people(session, group_id, user.id) if p.user_id == member_id)
    return changed


# ------------------------------------------------------------------------------ the library

_ITEM_SQL = """
  SELECT s.id, s.filename, s.kind, s.mime_type, s.size_bytes, s.note, s.status, s.created_at,
         s.shared_by, s.course_name, s.author, s.institution, s.rights,
         EXISTS (SELECT 1 FROM shared_item_reports r WHERE r.item_id = s.id AND r.reporter_id = :me) AS reported_by_me,
         (SELECT count(*) FROM shared_item_reports r WHERE r.item_id = s.id) AS report_count
  FROM shared_items s
"""


def _items_out(rows: list, names: dict[UUID, str], me: UUID, moderator: bool) -> list[ItemOut]:  # type: ignore[type-arg]
    return [
        ItemOut(
            id=r["id"], filename=r["filename"], kind=r["kind"], mime_type=r["mime_type"],
            size_bytes=r["size_bytes"], note=r["note"], status=r["status"],
            shared_by_name=names.get(r["shared_by"], ""), mine=r["shared_by"] == me,
            course_name=r["course_name"], author=r["author"], institution=r["institution"], rights=r["rights"],
            can_remove=r["shared_by"] == me or moderator,
            can_report=r["shared_by"] != me and not r["reported_by_me"],
            reported_by_me=r["reported_by_me"],
            reports=int(r["report_count"]) if moderator else None, created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/shareable-materials", response_model=list[ShareableOut])
async def shareable(_user: AuthUser, db: UserDbDep) -> list[ShareableOut]:
    """The student's own files they could put in a group."""
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT m.id, m.filename, m.kind, m.size_bytes, s.name AS subject_name "
                        "FROM materials m JOIN subjects s ON s.id = m.subject_id "
                        "WHERE m.deleted_at IS NULL ORDER BY s.name, m.filename LIMIT 300"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [ShareableOut(**r) for r in rows]


@router.get("/groups/{group_id}/items", response_model=list[ItemOut])
async def list_items(group_id: UUID, user: AuthUser, db: UserDbDep) -> list[ItemOut]:
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        rows = (
            (
                await session.execute(
                    text(f"{_ITEM_SQL} WHERE s.group_id = :g ORDER BY s.created_at DESC LIMIT 500"),
                    {"g": group_id, "me": user.id},
                )
            )
            .mappings()
            .all()
        )
        names = {p.user_id: p.display_name for p in await _people(session, group_id, user.id)}
    return _items_out(list(rows), names, user.id, is_admin(group.role))


async def _item(session: AsyncSession, group_id: UUID, item_id: UUID):  # type: ignore[no-untyped-def]
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, group_id, shared_by, filename, kind, mime_type, storage_key, status "
                    "FROM shared_items WHERE id = :i AND group_id = :g"
                ),
                {"i": item_id, "g": group_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "That file is not in this group.")
    return row


@router.post("/groups/{group_id}/items", status_code=201, response_model=ItemOut)
async def share_item(
    group_id: UUID, body: ShareIn, user: AuthUser, db: UserDbDep, storage: StorageDep, limiter: LimiterDep
) -> ItemOut:
    if not body.confirm_rights:
        raise AppError(422, "rights_required", "Confirm that you may share this file.")
    await limiter.check(f"group:share:{user.id}", 30, 3600)
    async with db.session() as session:
        group = await _group(session, group_id, user.id)
        total = (
            await session.execute(text("SELECT count(*) FROM shared_items WHERE group_id = :g"), {"g": group_id})
        ).scalar_one()
        if total >= MAX_ITEMS:
            raise AppError(409, "group_library_full", "This group's library is full.")
        material = (
            (
                await session.execute(
                    text(
                        "SELECT m.filename, m.kind, m.mime_type, m.size_bytes, m.storage_key, s.name AS course_name "
                        "FROM materials m LEFT JOIN subjects s ON s.id = m.subject_id "
                        "WHERE m.id = :id AND m.deleted_at IS NULL"
                    ),
                    {"id": body.material_id},
                )
            )
            .mappings()
            .first()
        )
        if material is None:
            raise AppError(404, "not_found", "Material not found.")
        twin = (
            await session.execute(
                text(
                    "SELECT 1 FROM shared_items WHERE group_id = :g AND shared_by = :u "
                    "AND filename = :f AND size_bytes IS NOT DISTINCT FROM :s"
                ),
                {"g": group_id, "u": user.id, "f": material["filename"], "s": material["size_bytes"]},
            )
        ).scalar_one_or_none()
        if twin is not None:
            raise AppError(409, "already_shared", "You already shared this file here.")

    extension = extension_of(material["filename"])
    if extension not in ALLOWED_TYPES:
        raise AppError(415, "unsupported_type", "This file type is not supported.")
    try:
        data = await asyncio.to_thread(storage.get_bytes, material["storage_key"])
    except Exception as exc:
        raise AppError(404, "not_found", "The file is no longer stored.") from exc
    if not looks_like(extension, data[:4096]):
        raise AppError(415, "unsupported_type", "This file does not match its type.")

    item_id = uuid4()
    key = f"shared/{group_id}/{item_id}.{extension}"
    await asyncio.to_thread(storage.put, key, io.BytesIO(data), ALLOWED_TYPES[extension])
    try:
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO shared_items (id, group_id, shared_by, filename, kind, mime_type, "
                    "size_bytes, storage_key, note, course_name, author, institution, rights) "
                    "VALUES (:id, :g, :u, :f, :k, :m, :s, :key, :n, :c, :a, :i, :r)"
                ),
                {
                    "id": item_id, "g": group_id, "u": user.id, "f": material["filename"],
                    "k": material["kind"], "m": ALLOWED_TYPES[extension], "s": len(data), "key": key,
                    "n": body.note, "c": material["course_name"], "a": body.author,
                    "i": body.institution, "r": body.rights,
                },
            )
            rows = (
                (await session.execute(text(f"{_ITEM_SQL} WHERE s.id = :id"), {"id": item_id, "me": user.id}))
                .mappings()
                .all()
            )
    except Exception:
        await _forget_files(storage, [key])
        raise
    return _items_out(list(rows), {user.id: user.display_name}, user.id, is_admin(group.role))[0]


@router.get("/groups/{group_id}/items/{item_id}/download")
async def download_item(
    group_id: UUID, item_id: UUID, _user: AuthUser, db: UserDbDep, storage: StorageDep
) -> StreamingResponse:
    async with db.session() as session:
        row = await _item(session, group_id, item_id)
    return StreamingResponse(
        storage.iter_bytes(row["storage_key"]),
        media_type=row["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": _disposition(row["filename"]), "X-Content-Type-Options": "nosniff"},
    )


@router.post("/groups/{group_id}/items/{item_id}/add", status_code=201, response_model=AddedOut)
async def add_to_subject(
    group_id: UUID, item_id: UUID, body: AddIn, user: AuthUser, db: UserDbDep, storage: StorageDep,
    queue: QueueDep, limiter: LimiterDep,
) -> AddedOut:
    """Copy a shared file into one of the student's own subjects. It is then read like any upload."""
    await limiter.check(f"group:add:{user.id}", 60, 3600)
    async with db.session() as session:
        item = await _item(session, group_id, item_id)
        if item["status"] != "active" and item["shared_by"] != user.id:
            raise AppError(404, "not_found", "That file is not in this group.")
        subject = (
            await session.execute(text("SELECT 1 FROM subjects WHERE id = :id"), {"id": body.subject_id})
        ).scalar_one_or_none()
        if subject is None:
            raise AppError(404, "not_found", "Subject not found.")
    extension = extension_of(item["filename"])
    if extension not in ALLOWED_TYPES:
        raise AppError(415, "unsupported_type", "This file type is not supported.")
    try:
        data = await asyncio.to_thread(storage.get_bytes, item["storage_key"])
    except Exception as exc:
        raise AppError(404, "not_found", "The file is no longer stored.") from exc
    if not looks_like(extension, data[:4096]):
        raise AppError(415, "unsupported_type", "This file does not match its type.")

    material_id = uuid4()
    key = f"materials/{user.id}/{material_id}.{extension}"
    await asyncio.to_thread(storage.put, key, io.BytesIO(data), ALLOWED_TYPES[extension])
    try:
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO materials (id, subject_id, owner_id, kind, filename, mime_type, "
                    "size_bytes, storage_key) VALUES (:id, :subject, :owner, :kind, :filename, "
                    ":mime, :size, :key)"
                ),
                {
                    "id": material_id, "subject": body.subject_id, "owner": user.id, "kind": item["kind"],
                    "filename": item["filename"], "mime": ALLOWED_TYPES[extension], "size": len(data), "key": key,
                },
            )
    except Exception:
        await _forget_files(storage, [key])
        raise
    try:
        await queue.enqueue_ingestion(material_id, user.id)
    except Exception:
        log.warning("Could not enqueue ingestion for %s", material_id, exc_info=True)
    return AddedOut(material_id=material_id, subject_id=body.subject_id)


@router.delete("/groups/{group_id}/items/{item_id}", status_code=204)
async def remove_item(
    group_id: UUID, item_id: UUID, user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    async with db.session() as session:
        await _group(session, group_id, user.id)
        key = (
            await session.execute(
                text("DELETE FROM shared_items WHERE id = :i AND group_id = :g RETURNING storage_key"),
                {"i": item_id, "g": group_id},
            )
        ).scalar_one_or_none()
    if key is None:
        raise AppError(404, "not_found", "That file is not in this group.")
    await _forget_files(storage, [key])
    return Response(status_code=204)


@router.post("/groups/{group_id}/items/{item_id}/report", response_model=ReportOut)
async def report_item(
    group_id: UUID, item_id: UUID, body: ReportIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> ReportOut:
    await limiter.check(f"group:report:{user.id}", 30, 3600)
    async with db.session() as session:
        item = await _item(session, group_id, item_id)
        if item["shared_by"] == user.id:
            raise AppError(409, "own_item", "You cannot report your own file.")
        result = (
            (
                await session.execute(
                    text("SELECT * FROM app_report_item(:i, :r, :n, :h)"),
                    {"i": item_id, "r": body.reason, "n": body.note, "h": HIDE_AT_REPORTS},
                )
            )
            .mappings()
            .first()
        )
    if result is None:
        raise AppError(404, "not_found", "That file is not in this group.")
    return ReportOut(hidden=bool(result["hidden"]))


@router.post("/groups/{group_id}/items/{item_id}/restore", response_model=ReportOut)
async def restore_item(group_id: UUID, item_id: UUID, user: AuthUser, db: UserDbDep) -> ReportOut:
    """An owner or admin decides a hidden file is fine: it shows again and the reports are cleared."""
    async with db.session() as session:
        await _admin_group(session, group_id, user.id)
        await _item(session, group_id, item_id)
        await session.execute(
            text("UPDATE shared_items SET status = 'active' WHERE id = :i AND group_id = :g"),
            {"i": item_id, "g": group_id},
        )
        await session.execute(text("DELETE FROM shared_item_reports WHERE item_id = :i"), {"i": item_id})
    return ReportOut(hidden=False)
