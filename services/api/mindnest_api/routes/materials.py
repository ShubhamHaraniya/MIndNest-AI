"""Uploading, listing, downloading and deleting study materials."""

import asyncio
import io
import logging
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from mindnest_core.filetypes import ALLOWED_TYPES, extension_of, looks_like
from mindnest_core.settings import get_settings
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, StorageDep, UserDbDep
from mindnest_api.errors import AppError

router = APIRouter(tags=["materials"])
logger = logging.getLogger("mindnest.materials")

Kind = Literal["material", "past_paper", "note", "assignment"]
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "text/plain"}


def clean_filename(name: str) -> str:
    """Display name only: no folders, no control characters, bounded length."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in unicodedata.normalize("NFC", name) if ch.isprintable())
    name = name.strip().strip(".")
    return name[:200] or "file"


class MaterialOut(BaseModel):
    id: UUID
    subject_id: UUID
    filename: str
    kind: Kind
    mime_type: str | None
    size_bytes: int | None
    status: Literal["uploaded", "processing", "ready", "failed"]
    # A short code (for example "no_text"), not prose, so the web app can show it in the
    # user's language.
    error: str | None
    stage: str | None
    language: Literal["en", "hi", "gu"] | None
    chunk_count: int
    module: str | None
    last_opened_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MaterialPatch(BaseModel):
    """Fields a student may change on a file. `module` set to null or an empty string clears it."""

    module: str | None = Field(default=None, max_length=80)
    kind: Kind | None = None


_SELECT = """
  SELECT m.id, m.subject_id, m.filename, m.kind, m.mime_type, m.size_bytes, m.status,
         m.error, m.language, m.module, m.last_opened_at, m.created_at, m.updated_at,
         (SELECT j.stage FROM ingestion_jobs j WHERE j.material_id = m.id
            ORDER BY j.created_at DESC LIMIT 1) AS stage,
         (SELECT count(*) FROM chunks c WHERE c.material_id = m.id) AS chunk_count
  FROM materials m
  WHERE m.deleted_at IS NULL
"""


async def _fetch(session: AsyncSession, material_id: UUID) -> MaterialOut:
    row = (
        (await session.execute(text(f"{_SELECT} AND m.id = :id"), {"id": material_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Material not found.")
    return MaterialOut(**row)


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    parts: list[bytes] = []
    total = 0
    while part := await file.read(1024 * 1024):
        total += len(part)
        if total > limit:
            raise AppError(413, "file_too_large", "That file is larger than the upload limit.")
        parts.append(part)
    return b"".join(parts)


@router.post("/subjects/{subject_id}/materials", status_code=201, response_model=MaterialOut)
async def upload_material(
    subject_id: UUID,
    request: Request,
    user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    queue: QueueDep,
    limiter: LimiterDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Kind, Form()] = "material",
    module: Annotated[str | None, Form(max_length=80)] = None,
) -> MaterialOut:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 1024:
        raise AppError(413, "file_too_large", "That file is larger than the upload limit.")
    await limiter.check(f"upload:{user.id}", 60, 3600)

    filename = clean_filename(file.filename or "file")
    extension = extension_of(filename)
    if extension not in ALLOWED_TYPES:
        raise AppError(415, "unsupported_type", "This file type is not supported.")

    data = await _read_limited(file, limit)
    if not data:
        raise AppError(422, "empty_file", "That file is empty.")
    if not looks_like(extension, data[:4096]):
        raise AppError(415, "unsupported_type", "This file does not match its type.")

    # The subject must be visible to this user (row-level security hides everyone else's).
    async with db.session() as session:
        found = (
            await session.execute(text("SELECT 1 FROM subjects WHERE id = :id"), {"id": subject_id})
        ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Subject not found.")

    material_id = uuid4()
    # The key never contains the user's filename, so odd names cannot cause path problems.
    storage_key = f"materials/{user.id}/{material_id}.{extension}"
    mime = ALLOWED_TYPES[extension]
    await asyncio.to_thread(storage.put, storage_key, io.BytesIO(data), mime)
    try:
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO materials (id, subject_id, owner_id, kind, filename, mime_type, "
                    "size_bytes, storage_key, module) VALUES (:id, :subject, :owner, :kind, :filename, "
                    ":mime, :size, :key, :module)"
                ),
                {
                    "id": material_id,
                    "subject": subject_id,
                    "owner": user.id,
                    "kind": kind,
                    "filename": filename,
                    "mime": mime,
                    "size": len(data),
                    "key": storage_key,
                    "module": (module or "").strip() or None,
                },
            )
            material = await _fetch(session, material_id)
    except Exception:
        await asyncio.to_thread(storage.delete, storage_key)
        raise

    try:
        await queue.enqueue_ingestion(material_id, user.id)
    except Exception:
        # The file is safe and the row exists; the user can press Retry.
        logger.warning("Could not enqueue ingestion for %s", material_id, exc_info=True)
    return material


@router.get("/subjects/{subject_id}/materials", response_model=list[MaterialOut])
async def list_materials(subject_id: UUID, _user: AuthUser, db: UserDbDep) -> list[MaterialOut]:
    async with db.session() as session:
        visible = (
            await session.execute(text("SELECT 1 FROM subjects WHERE id = :id"), {"id": subject_id})
        ).scalar_one_or_none()
        if visible is None:
            raise AppError(404, "not_found", "Subject not found.")
        rows = (
            (
                await session.execute(
                    text(f"{_SELECT} AND m.subject_id = :id ORDER BY m.created_at DESC LIMIT 500"),
                    {"id": subject_id},
                )
            )
            .mappings()
            .all()
        )
    return [MaterialOut(**row) for row in rows]


@router.get("/materials/{material_id}", response_model=MaterialOut)
async def get_material(material_id: UUID, _user: AuthUser, db: UserDbDep) -> MaterialOut:
    async with db.session() as session:
        return await _fetch(session, material_id)


@router.get("/materials/{material_id}/download")
async def download_material(
    material_id: UUID,
    _user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    inline: bool = False,
) -> StreamingResponse:
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT filename, storage_key, mime_type FROM materials "
                        "WHERE id = :id AND deleted_at IS NULL"
                    ),
                    {"id": material_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise AppError(404, "not_found", "Material not found.")
    async with db.session() as session:
        await session.execute(
            text("UPDATE materials SET last_opened_at = now() WHERE id = :id"), {"id": material_id}
        )
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", row["filename"]) or "file"
    # Only types a browser can show safely are ever served inline (for the preview pane); anything
    # else, and every download, stays an attachment.
    show_inline = inline and row["mime_type"] in INLINE_TYPES
    disposition = f"{'inline' if show_inline else 'attachment'}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row['filename'])}"
    headers = {"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"}
    if show_inline:
        # The preview pane is a frame on this same site; nobody else may frame the file.
        headers["X-Frame-Options"] = "SAMEORIGIN"
        headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return StreamingResponse(
        storage.iter_bytes(row["storage_key"]),
        media_type=row["mime_type"] or "application/octet-stream",
        headers=headers,
    )


@router.post("/materials/{material_id}/open", status_code=204)
async def mark_opened(material_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    """The student looked at this file (or inspected a chat source from it)."""
    async with db.session() as session:
        found = (
            await session.execute(
                text(
                    "UPDATE materials SET last_opened_at = now() "
                    "WHERE id = :id AND deleted_at IS NULL RETURNING 1"
                ),
                {"id": material_id},
            )
        ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Material not found.")
    return Response(status_code=204)


@router.patch("/materials/{material_id}", response_model=MaterialOut)
async def update_material(material_id: UUID, body: MaterialPatch, _user: AuthUser, db: UserDbDep) -> MaterialOut:
    async with db.session() as session:
        await _fetch(session, material_id)  # 404 for anything that is not the student's own
        if "module" in body.model_fields_set:
            await session.execute(
                text("UPDATE materials SET module = :m, updated_at = now() WHERE id = :id"),
                {"m": (body.module or "").strip() or None, "id": material_id},
            )
        if body.kind is not None:
            await session.execute(
                text("UPDATE materials SET kind = :k, updated_at = now() WHERE id = :id"),
                {"k": body.kind, "id": material_id},
            )
        return await _fetch(session, material_id)


@router.post("/materials/{material_id}/retry", response_model=MaterialOut)
async def retry_material(
    material_id: UUID, user: AuthUser, db: UserDbDep, queue: QueueDep
) -> MaterialOut:
    async with db.session() as session:
        current = await _fetch(session, material_id)
        if current.status not in {"failed", "uploaded"}:
            raise AppError(409, "not_retryable", "This material is already being processed.")
        await session.execute(
            text(
                "UPDATE materials SET status = 'uploaded', error = NULL, updated_at = now() "
                "WHERE id = :id"
            ),
            {"id": material_id},
        )
        material = await _fetch(session, material_id)
    try:
        await queue.enqueue_ingestion(material_id, user.id)
    except Exception:
        logger.warning("Could not enqueue ingestion for %s", material_id, exc_info=True)
    return material


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(
    material_id: UUID, _user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    async with db.session() as session:
        key = (
            await session.execute(
                text("DELETE FROM materials WHERE id = :id RETURNING storage_key"),
                {"id": material_id},
            )
        ).scalar_one_or_none()
    if key is None:
        raise AppError(404, "not_found", "Material not found.")
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        logger.warning("Could not delete stored file %s", key, exc_info=True)
    return Response(status_code=204)
