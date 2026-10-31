"""The Materials Library: notes, past papers and other files students choose to share beyond a group.

Three audiences, picked by the student for each file:

* private    - only the owner (a draft; never searchable by anyone else);
* institution - students who typed the same institution name in Settings;
* public     - everyone, after a moderator approves it.

What is published is a COPY of the file, so the original can change or go away and a takedown
removes exactly what was shared. Copies that students add to their own courses are ordinary private
materials; a takedown also pulls those out of the retrieval index (migration 0018). Row-level
security decides who may read a row; the checks here give clear errors on top of that.
"""

import asyncio
import io
import logging
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from mindnest_core.filetypes import ALLOWED_TYPES, extension_of, looks_like
from mindnest_core.librarylogic import (
    HOLD_AT_REPORTS,
    MAX_ITEMS_PER_USER,
    is_wider,
    material_kind,
    status_for_owner_change,
)
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, StorageDep, UserDbDep
from mindnest_api.errors import AppError

router = APIRouter(tags=["library"])
log = logging.getLogger("mindnest.library")

DocType = Literal["notes", "past_paper", "textbook", "slides", "reference", "other"]
Visibility = Literal["private", "institution", "public"]
Scope = Literal["college", "others", "global", "mine"]
Rights = Literal["own_work", "permitted", "open_licence"]
Reason = Literal["copyright", "inappropriate", "wrong_content", "other"]
ItemStatus = Literal["draft", "pending_review", "published", "rejected", "held", "taken_down"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Term = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]

INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "text/plain"}


# ------------------------------------------------------------------------------ schemas


class ItemOut(BaseModel):
    id: UUID
    title: str
    description: str
    doc_type: DocType
    course_name: str
    topic: str
    semester: str
    academic_year: str
    author: str
    institution: str
    rights: Rights
    visibility: Visibility
    status: ItemStatus
    # Why a moderator turned it down (only the owner sees an item in that state).
    review_note: str
    filename: str
    mime_type: str | None
    size_bytes: int | None
    previewable: bool
    mine: bool
    reported_by_me: bool
    published_at: datetime | None
    created_at: datetime


class PageOut(BaseModel):
    items: list[ItemOut]
    total: int
    # The institution the student declared, so the page can ask for one when "My college" is empty.
    my_institution: str


class FacetsOut(BaseModel):
    courses: list[str]
    topics: list[str]
    semesters: list[str]
    years: list[str]
    institutions: list[str]


class PublishIn(BaseModel):
    material_id: UUID
    title: Title | None = None
    description: Description = ""
    doc_type: DocType = "notes"
    course_name: Short | None = None
    topic: Short = ""
    semester: Term = ""
    academic_year: Term = ""
    author: Short = ""
    rights: Rights = "own_work"
    visibility: Visibility = "private"
    # The student confirms they may share this file; required for anything wider than private.
    confirm_rights: bool = False


class PatchIn(BaseModel):
    title: Title | None = None
    description: Description | None = None
    doc_type: DocType | None = None
    course_name: Short | None = None
    topic: Short | None = None
    semester: Term | None = None
    academic_year: Term | None = None
    author: Short | None = None
    rights: Rights | None = None
    visibility: Visibility | None = None
    confirm_rights: bool = False


class AddIn(BaseModel):
    subject_id: UUID


class AddedOut(BaseModel):
    material_id: UUID
    subject_id: UUID


class ReportIn(BaseModel):
    reason: Reason
    note: Note = ""


class ReportOut(BaseModel):
    held: bool


class InstitutionOut(BaseModel):
    name: str
    students: int


# ------------------------------------------------------------------------------ helpers

_SELECT = """
  SELECT i.id, i.title, i.description, i.doc_type, i.course_name, i.topic, i.semester,
         i.academic_year, i.author, i.institution, i.rights, i.visibility, i.status,
         CASE WHEN i.owner_id = :me THEN i.review_note ELSE '' END AS review_note,
         i.filename, i.mime_type, i.size_bytes, i.published_at, i.created_at,
         (i.owner_id = :me) AS mine,
         EXISTS (SELECT 1 FROM library_reports r
                 WHERE r.item_id = i.id AND r.reporter_id = :me) AS reported_by_me
  FROM library_items i
"""

# Which rows each tab shows. :mykey is the student's own institution (normalised, may be empty).
_SCOPES = {
    "college": "i.status = 'published' AND i.visibility IN ('institution', 'public') "
    "AND :mykey <> '' AND i.institution_key = :mykey",
    "others": "i.status = 'published' AND i.visibility = 'public' "
    "AND i.institution_key <> '' AND i.institution_key <> :mykey",
    "global": "i.status = 'published' AND i.visibility = 'public' AND i.rights = 'open_licence'",
    "mine": "i.owner_id = :me",
}


def _out(row: dict) -> ItemOut:  # type: ignore[type-arg]
    return ItemOut(**row, previewable=(row["mime_type"] or "") in INLINE_TYPES)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _my_key(session: AsyncSession) -> str:
    return (await session.execute(text("SELECT app_my_institution_key()"))).scalar_one() or ""


async def _item(session: AsyncSession, item_id: UUID, me: UUID) -> ItemOut:
    row = (
        (await session.execute(text(f"{_SELECT} WHERE i.id = :id"), {"id": item_id, "me": me}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "That file is not in the library.")
    return _out(dict(row))


async def _forget_files(storage: StorageDep, keys: list[str]) -> None:
    for key in keys:
        if not key:
            continue
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            log.warning("could not delete stored file %s", key, exc_info=True)


def _disposition(filename: str, inline: bool) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename) or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# ------------------------------------------------------------------------------ browsing


@router.get("/library", response_model=PageOut)
async def browse(
    user: AuthUser,
    db: UserDbDep,
    scope: Scope = "college",
    q: Annotated[str, Query(max_length=100)] = "",
    course: Annotated[str, Query(max_length=120)] = "",
    topic: Annotated[str, Query(max_length=120)] = "",
    semester: Annotated[str, Query(max_length=20)] = "",
    year: Annotated[str, Query(max_length=20)] = "",
    institution: Annotated[str, Query(max_length=120)] = "",
    doc_type: DocType | None = None,
    sort: Literal["newest", "title"] = "newest",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> PageOut:
    clauses = [_SCOPES[scope]]
    params: dict[str, object] = {"me": user.id, "limit": limit, "offset": offset}
    if q.strip():
        params["q"] = _like(q.strip())
        clauses.append(
            "(i.title ILIKE :q OR i.description ILIKE :q OR i.course_name ILIKE :q "
            "OR i.topic ILIKE :q OR i.author ILIKE :q OR i.filename ILIKE :q)"
        )
    for name, column, value in (
        ("course", "i.course_name", course),
        ("topic", "i.topic", topic),
        ("semester", "i.semester", semester),
        ("year", "i.academic_year", year),
    ):
        if value.strip():
            params[name] = value.strip()
            clauses.append(f"lower({column}) = lower(:{name})")
    if institution.strip():
        params["institution"] = institution.strip()
        clauses.append("i.institution_key = app_inst_key(:institution)")
    if doc_type:
        params["doc_type"] = doc_type
        clauses.append("i.doc_type = :doc_type")
    where = " AND ".join(clauses)
    order = (
        "lower(i.title), i.id"
        if sort == "title"
        else "COALESCE(i.published_at, i.created_at) DESC, i.id"
    )

    async with db.session() as session:
        params["mykey"] = await _my_key(session)
        total = (
            await session.execute(
                text(f"SELECT count(*) FROM library_items i WHERE {where}"),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            )
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    text(f"{_SELECT} WHERE {where} ORDER BY {order} LIMIT :limit OFFSET :offset"),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return PageOut(
        items=[_out(dict(row)) for row in rows], total=total, my_institution=user.institution_name
    )


@router.get("/library/facets", response_model=FacetsOut)
async def facets(user: AuthUser, db: UserDbDep, scope: Scope = "college") -> FacetsOut:
    """The values students can filter a tab by: only what is actually in that tab."""
    async with db.session() as session:
        params = {"me": user.id, "mykey": await _my_key(session)}
        out: dict[str, list[str]] = {}
        for name, column in (
            ("courses", "course_name"),
            ("topics", "topic"),
            ("semesters", "semester"),
            ("years", "academic_year"),
            ("institutions", "institution"),
        ):
            rows = await session.execute(
                text(
                    f"SELECT DISTINCT i.{column} FROM library_items i "
                    f"WHERE {_SCOPES[scope]} AND i.{column} <> '' ORDER BY 1 LIMIT 100"
                ),
                params,
            )
            out[name] = [value for (value,) in rows.all()]
    return FacetsOut(**out)


@router.get("/library/institutions", response_model=list[InstitutionOut])
async def institutions(
    _user: AuthUser, db: UserDbDep, q: Annotated[str, Query(max_length=60)] = ""
) -> list[InstitutionOut]:
    """Suggestions while typing an institution name (only names that two or more students use)."""
    async with db.session() as session:
        rows = (
            (await session.execute(text("SELECT * FROM app_institution_names(:q, 10)"), {"q": q}))
            .mappings()
            .all()
        )
    return [InstitutionOut(name=r["name"], students=r["students"]) for r in rows]


@router.get("/library/{item_id}", response_model=ItemOut)
async def get_item(item_id: UUID, user: AuthUser, db: UserDbDep) -> ItemOut:
    async with db.session() as session:
        return await _item(session, item_id, user.id)


@router.get("/library/{item_id}/file")
async def open_file(
    item_id: UUID,
    _user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    inline: bool = False,
) -> StreamingResponse:
    """The file itself. `inline` shows PDFs, images and text in the browser (a preview); anything
    else is always a download."""
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text("SELECT filename, mime_type, storage_key FROM library_items WHERE id = :i"),
                    {"i": item_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None or not row["storage_key"]:
        raise AppError(404, "not_found", "That file is not in the library.")
    mime = row["mime_type"] or "application/octet-stream"
    show = inline and mime in INLINE_TYPES
    return StreamingResponse(
        storage.iter_bytes(row["storage_key"]),
        media_type=mime,
        headers={
            "Content-Disposition": _disposition(row["filename"], show),
            "X-Content-Type-Options": "nosniff",
            # The preview pane frames this response from our own pages (and only those).
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "frame-ancestors 'self'",
            "Cache-Control": "private, no-store",
        },
    )


# ------------------------------------------------------------------------------ publishing


@router.post("/library", status_code=201, response_model=ItemOut)
async def publish(
    body: PublishIn, user: AuthUser, db: UserDbDep, storage: StorageDep, limiter: LimiterDep
) -> ItemOut:
    """Copy one of the student's materials into the library with the audience they choose."""
    await limiter.check(f"library:publish:{user.id}", 20, 3600)
    if body.visibility != "private" and not body.confirm_rights:
        raise AppError(422, "confirm_rights", "Confirm that you may share this file.")
    if body.visibility == "institution" and not user.institution_name:
        raise AppError(422, "institution_required", "Set your institution in Settings first.")

    async with db.session() as session:
        material = (
            (
                await session.execute(
                    text(
                        "SELECT m.filename, m.kind, m.mime_type, m.size_bytes, m.storage_key, "
                        "s.name AS subject_name FROM materials m "
                        "LEFT JOIN subjects s ON s.id = m.subject_id "
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
        if material["kind"] == "assignment":
            raise AppError(422, "assignment_not_shareable", "Assignment files cannot be shared.")
        count = (
            await session.execute(
                text("SELECT count(*) FROM library_items WHERE owner_id = :u"), {"u": user.id}
            )
        ).scalar_one()
        if count >= MAX_ITEMS_PER_USER:
            raise AppError(409, "library_full", "You have reached the limit for library files.")

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
    key = f"library/{user.id}/{item_id}.{extension}"
    await asyncio.to_thread(storage.put, key, io.BytesIO(data), ALLOWED_TYPES[extension])
    status = status_for_owner_change(body.visibility)
    try:
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO library_items (id, owner_id, source_material_id, title, description, "
                    "doc_type, course_name, topic, semester, academic_year, author, institution, "
                    "institution_key, rights, visibility, status, filename, mime_type, size_bytes, "
                    "storage_key, published_at) VALUES (:id, :owner, :source, :title, :description, "
                    ":doc_type, :course, :topic, :semester, :year, :author, :institution, "
                    "app_my_institution_key(), :rights, :visibility, :status, :filename, :mime, "
                    ":size, :key, CASE WHEN :status = 'published' THEN now() END)"
                ),
                {
                    "id": item_id,
                    "owner": user.id,
                    "source": body.material_id,
                    "title": body.title or re.sub(r"\.[^.]+$", "", material["filename"])[:160],
                    "description": body.description,
                    "doc_type": body.doc_type,
                    "course": body.course_name
                    if body.course_name is not None
                    else (material["subject_name"] or "")[:120],
                    "topic": body.topic,
                    "semester": body.semester,
                    "year": body.academic_year,
                    "author": body.author,
                    "institution": user.institution_name,
                    "rights": body.rights,
                    "visibility": body.visibility,
                    "status": status,
                    "filename": material["filename"],
                    "mime": ALLOWED_TYPES[extension],
                    "size": len(data),
                    "key": key,
                },
            )
            return await _item(session, item_id, user.id)
    except IntegrityError as exc:
        await _forget_files(storage, [key])
        raise AppError(409, "already_published", "This file is already in the library.") from exc
    except Exception:
        await _forget_files(storage, [key])
        raise


@router.patch("/library/{item_id}", response_model=ItemOut)
async def update_item(item_id: UUID, body: PatchIn, user: AuthUser, db: UserDbDep) -> ItemOut:
    """Edit the description or change the audience. Public items go back to review after any edit."""
    changes = body.model_dump(exclude_unset=True, exclude={"confirm_rights"})
    for key, value in changes.items():
        if value is None:
            raise AppError(422, "validation_error", f"{key} cannot be empty.")
    async with db.session() as session:
        item = await _item(session, item_id, user.id)
        if not item.mine:
            raise AppError(404, "not_found", "That file is not in the library.")
        if item.status in ("held", "taken_down"):
            raise AppError(409, "locked", "A moderator is reviewing this file.")
        current = item.model_dump()
        changes = {k: v for k, v in changes.items() if current.get(k) != v}
        # Saving a rejected item without changes sends it for review again.
        if not changes and item.status != "rejected":
            return item
        visibility = changes.get("visibility", item.visibility)
        if is_wider(item.visibility, visibility) and not body.confirm_rights:
            raise AppError(422, "confirm_rights", "Confirm that you may share this file.")
        if visibility == "institution" and not user.institution_name:
            raise AppError(422, "institution_required", "Set your institution in Settings first.")

        status = status_for_owner_change(visibility)
        assignments = [f"{column} = :{column}" for column in changes]
        params: dict[str, object] = {**changes, "id": item_id, "status": status}
        assignments.append("status = :status")
        if visibility != "private":
            params["institution"] = user.institution_name
            assignments.append("institution = :institution")
            assignments.append("institution_key = app_my_institution_key()")
        if status == "published":
            assignments.append("published_at = COALESCE(published_at, now())")
        assignments.append("updated_at = now()")
        await session.execute(
            text(f"UPDATE library_items SET {', '.join(assignments)} WHERE id = :id"), params
        )
        return await _item(session, item_id, user.id)


@router.delete("/library/{item_id}", status_code=204)
async def delete_item(
    item_id: UUID, user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    """Withdraw a file. Copies other students already added to their courses stay with them."""
    async with db.session() as session:
        key = (
            await session.execute(
                text("DELETE FROM library_items WHERE id = :i AND owner_id = :me RETURNING storage_key"),
                {"i": item_id, "me": user.id},
            )
        ).scalar_one_or_none()
    if key is None:
        raise AppError(404, "not_found", "That file is not in the library.")
    await _forget_files(storage, [key])
    return Response(status_code=204)


# ------------------------------------------------------------------------------ using a file


@router.post("/library/{item_id}/add", status_code=201, response_model=AddedOut)
async def add_to_course(
    item_id: UUID,
    body: AddIn,
    user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    queue: QueueDep,
    limiter: LimiterDep,
) -> AddedOut:
    """Copy a library file into one of the student's own subjects, where it is read like any upload."""
    await limiter.check(f"library:add:{user.id}", 60, 3600)
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT filename, doc_type, storage_key, status, owner_id "
                        "FROM library_items WHERE id = :i"
                    ),
                    {"i": item_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or not row["storage_key"]:
            raise AppError(404, "not_found", "That file is not in the library.")
        if row["status"] != "published" and row["owner_id"] != user.id:
            raise AppError(404, "not_found", "That file is not in the library.")
        subject = (
            await session.execute(text("SELECT 1 FROM subjects WHERE id = :id"), {"id": body.subject_id})
        ).scalar_one_or_none()
        if subject is None:
            raise AppError(404, "not_found", "Subject not found.")
    extension = extension_of(row["filename"])
    if extension not in ALLOWED_TYPES:
        raise AppError(415, "unsupported_type", "This file type is not supported.")
    try:
        data = await asyncio.to_thread(storage.get_bytes, row["storage_key"])
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
                    "size_bytes, storage_key, library_item_id) VALUES (:id, :subject, :owner, :kind, "
                    ":filename, :mime, :size, :key, :item)"
                ),
                {
                    "id": material_id,
                    "subject": body.subject_id,
                    "owner": user.id,
                    "kind": material_kind(row["doc_type"]),
                    "filename": row["filename"],
                    "mime": ALLOWED_TYPES[extension],
                    "size": len(data),
                    "key": key,
                    "item": item_id,
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


@router.post("/library/{item_id}/report", response_model=ReportOut)
async def report_item(
    item_id: UUID, body: ReportIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> ReportOut:
    await limiter.check(f"library:report:{user.id}", 30, 3600)
    async with db.session() as session:
        item = await _item(session, item_id, user.id)
        if item.mine:
            raise AppError(409, "own_item", "You cannot report your own file.")
        result = (
            (
                await session.execute(
                    text("SELECT * FROM app_library_report(:i, :r, :n, :h)"),
                    {"i": item_id, "r": body.reason, "n": body.note, "h": HOLD_AT_REPORTS},
                )
            )
            .mappings()
            .first()
        )
    if result is None:
        raise AppError(404, "not_found", "That file is not in the library.")
    return ReportOut(held=bool(result["held"]))
