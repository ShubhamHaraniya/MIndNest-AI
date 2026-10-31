"""Subjects: the courses a student organises their materials under."""

import asyncio
import base64
import binascii
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, StorageDep, UserDbDep
from mindnest_api.errors import AppError

router = APIRouter(prefix="/subjects", tags=["subjects"])
logger = logging.getLogger("mindnest.subjects")

# Every query below runs inside db.session(), so row-level security limits it to the signed-in
# user's rows. The explicit owner checks that other apps add are deliberately not repeated here:
# a subject that belongs to someone else is simply not visible, and answers 404.

_SELECT = """
  SELECT s.id, s.name, s.course_code, s.semester, s.description, s.archived_at,
         s.created_at, s.updated_at,
         (SELECT count(*) FROM materials m
            WHERE m.subject_id = s.id AND m.deleted_at IS NULL) AS material_count
  FROM subjects s
"""


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class SubjectIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    course_code: Annotated[str, Field(max_length=40)] | None = None
    semester: Annotated[str, Field(max_length=40)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("course_code", "semester", "description")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SubjectUpdate(BaseModel):
    """Only fields that are present change. Send null (or blank) to clear an optional field."""

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    course_code: Annotated[str, Field(max_length=40)] | None = None
    semester: Annotated[str, Field(max_length=40)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("course_code", "semester", "description")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SubjectOut(BaseModel):
    id: UUID
    name: str
    course_code: str | None
    semester: str | None
    description: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    material_count: int


class SubjectPage(BaseModel):
    items: list[SubjectOut]
    next_cursor: str | None
    total: int


class DeleteImpact(BaseModel):
    materials: int
    topics: int
    conversations_kept: int


def _encode_cursor(created_at: datetime, subject_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{subject_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at, subject_id = raw.split("|", 1)
        return datetime.fromisoformat(created_at), UUID(subject_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(422, "invalid_cursor", "The page cursor is not valid.") from exc


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _fetch(session: AsyncSession, subject_id: UUID) -> SubjectOut:
    row = (
        (await session.execute(text(f"{_SELECT} WHERE s.id = :id"), {"id": subject_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Subject not found.")
    return SubjectOut(**row)


@router.get("", response_model=SubjectPage)
async def list_subjects(
    _user: AuthUser,
    db: UserDbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    state: Literal["active", "archived", "all"] = "active",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> SubjectPage:
    # Conditions are fixed strings chosen here; user input only ever travels as bound parameters.
    conditions: list[str] = []
    params: dict[str, object] = {}
    if state == "active":
        conditions.append("s.archived_at IS NULL")
    elif state == "archived":
        conditions.append("s.archived_at IS NOT NULL")
    if q and q.strip():
        conditions.append(r"(s.name ILIKE :q ESCAPE '\' OR s.course_code ILIKE :q ESCAPE '\')")
        params["q"] = _like_pattern(q.strip())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    page_conditions = list(conditions)
    page_params = dict(params)
    if cursor:
        c_at, c_id = _decode_cursor(cursor)
        page_conditions.append("(s.created_at, s.id) < (CAST(:c_at AS timestamptz), CAST(:c_id AS uuid))")
        page_params["c_at"] = c_at
        page_params["c_id"] = str(c_id)
    page_where = f"WHERE {' AND '.join(page_conditions)}" if page_conditions else ""

    async with db.session() as session:
        total = (
            await session.execute(text(f"SELECT count(*) FROM subjects s {where}"), params)
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    text(f"{_SELECT} {page_where} ORDER BY s.created_at DESC, s.id DESC LIMIT :limit"),
                    {**page_params, "limit": limit + 1},
                )
            )
            .mappings()
            .all()
        )
    items = [SubjectOut(**row) for row in rows[:limit]]
    next_cursor = (
        _encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > limit and items else None
    )
    return SubjectPage(items=items, next_cursor=next_cursor, total=total)


@router.post("", status_code=201, response_model=SubjectOut)
async def create_subject(body: SubjectIn, user: AuthUser, db: UserDbDep) -> SubjectOut:
    async with db.session() as session:
        subject_id = (
            await session.execute(
                text(
                    "INSERT INTO subjects (owner_id, name, course_code, semester, description) "
                    "VALUES (:owner, :name, :course_code, :semester, :description) RETURNING id"
                ),
                {
                    "owner": user.id,
                    "name": body.name,
                    "course_code": body.course_code,
                    "semester": body.semester,
                    "description": body.description,
                },
            )
        ).scalar_one()
        return await _fetch(session, subject_id)


@router.get("/{subject_id}", response_model=SubjectOut)
async def get_subject(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> SubjectOut:
    async with db.session() as session:
        return await _fetch(session, subject_id)


@router.patch("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: UUID, body: SubjectUpdate, _user: AuthUser, db: UserDbDep
) -> SubjectOut:
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise AppError(422, "validation_error", "Name cannot be null.")
    async with db.session() as session:
        if changes:
            assignments = [f"{column} = :{column}" for column in changes]  # keys come from the model
            updated = (
                await session.execute(
                    text(
                        f"UPDATE subjects SET {', '.join(assignments)}, updated_at = now() "
                        "WHERE id = :id RETURNING id"
                    ),
                    {**changes, "id": subject_id},
                )
            ).scalar_one_or_none()
            if updated is None:
                raise AppError(404, "not_found", "Subject not found.")
        return await _fetch(session, subject_id)


async def _set_archived(db: UserDbDep, subject_id: UUID, archived: bool) -> SubjectOut:
    value = "COALESCE(archived_at, now())" if archived else "NULL"
    async with db.session() as session:
        updated = (
            await session.execute(
                text(
                    f"UPDATE subjects SET archived_at = {value}, updated_at = now() "
                    "WHERE id = :id RETURNING id"
                ),
                {"id": subject_id},
            )
        ).scalar_one_or_none()
        if updated is None:
            raise AppError(404, "not_found", "Subject not found.")
        return await _fetch(session, subject_id)


@router.post("/{subject_id}/archive", response_model=SubjectOut)
async def archive_subject(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> SubjectOut:
    return await _set_archived(db, subject_id, True)


@router.post("/{subject_id}/unarchive", response_model=SubjectOut)
async def unarchive_subject(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> SubjectOut:
    return await _set_archived(db, subject_id, False)


async def _impact(session: AsyncSession, subject_id: UUID) -> DeleteImpact:
    await _fetch(session, subject_id)  # 404 if missing or not the caller's
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM materials
                         WHERE subject_id = :id AND deleted_at IS NULL) AS materials,
                      (SELECT count(*) FROM topics WHERE subject_id = :id) AS topics,
                      (SELECT count(*) FROM conversations WHERE subject_id = :id)
                         AS conversations_kept
                    """
                ),
                {"id": subject_id},
            )
        )
        .mappings()
        .one()
    )
    return DeleteImpact(**row)


@router.get("/{subject_id}/delete-impact", response_model=DeleteImpact)
async def delete_impact(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> DeleteImpact:
    """What deleting would remove, so the dialog can show it before the user confirms."""
    async with db.session() as session:
        return await _impact(session, subject_id)


@router.delete("/{subject_id}", status_code=204)
async def delete_subject(
    subject_id: UUID,
    _user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    confirm: bool = False,
) -> Response:
    async with db.session() as session:
        impact = await _impact(session, subject_id)
        if not confirm:
            raise AppError(
                400,
                "confirmation_required",
                "Deleting a subject also deletes its materials. Pass confirm=true to proceed.",
                details=impact.model_dump(),
            )
        storage_keys = (
            (
                await session.execute(
                    text("SELECT storage_key FROM materials WHERE subject_id = :id"),
                    {"id": subject_id},
                )
            )
            .scalars()
            .all()
        )
        # Materials, topics and chunks go with the subject (ON DELETE CASCADE); chat history
        # stays, detached from the subject.
        await session.execute(text("DELETE FROM subjects WHERE id = :id"), {"id": subject_id})
    # The database is the source of truth, so files are removed only after it commits. A failure
    # here leaves an orphaned file, which is logged and harmless; the reverse would lose data.
    for key in storage_keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            logger.warning("Could not delete stored file %s", key, exc_info=True)
    return Response(status_code=204)
