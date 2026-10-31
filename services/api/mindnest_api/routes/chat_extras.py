"""Chat extras: what a conversation may search, files attached to it, thumbs up/down on answers,
and the earlier versions of an answer that was written again."""

import asyncio
import io
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Request, Response, UploadFile
from mindnest_core.chatlogic import (
    ATTACHMENT_TYPES,
    MAX_ATTACHMENT_BYTES,
    ChatRuleError,
    check_attachment,
    is_word_document,
    resolve_scope,
    validate_feedback,
)
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, StorageDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.routes.chat import (
    _CONVERSATION_COLUMNS,
    ConversationOut,
    _as_blocks,
    _get_conversation,
    _text_of,
)
from mindnest_api.routes.materials import _read_limited, clean_filename

router = APIRouter(tags=["chat"])
logger = logging.getLogger("mindnest.chat")

# How a broken rule is reported: the code is stable (the web app shows it in the student's language).
_RULE_STATUS = {
    "too_many_attachments": 409,
    "unsupported_type": 415,
    "type_mismatch": 415,
    "file_too_large": 413,
    "empty_file": 422,
    "not_last_answer": 409,
    "no_question": 409,
}


def rule_error(exc: ChatRuleError) -> AppError:
    return AppError(_RULE_STATUS.get(exc.code, 422), exc.code, f"Not allowed: {exc.code.replace('_', ' ')}.")


# ----------------------------------------------------------------------------------------- scope


class ScopeIn(BaseModel):
    scope: Literal["all", "subject", "materials"]
    subject_id: UUID | None = None
    material_ids: list[UUID] = Field(default_factory=list, max_length=50)


@router.patch("/conversations/{conversation_id}/scope", response_model=ConversationOut)
async def set_scope(
    conversation_id: UUID, body: ScopeIn, _user: AuthUser, db: UserDbDep
) -> ConversationOut:
    """Choose what this conversation may search: every course, one course, or chosen files."""
    try:
        scope = resolve_scope(body.scope, body.subject_id, body.material_ids)
    except ChatRuleError as exc:
        raise rule_error(exc) from exc
    async with db.session() as session:
        await _get_conversation(session, conversation_id)
        if scope.kind == "subject":
            visible = (
                await session.execute(
                    text("SELECT 1 FROM subjects WHERE id = :id AND archived_at IS NULL"),
                    {"id": scope.subject_id},
                )
            ).scalar_one_or_none()
            if visible is None:
                raise AppError(404, "not_found", "Subject not found.")
        if scope.kind == "materials":
            found = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM materials WHERE id = ANY(CAST(:ids AS uuid[])) "
                        "AND deleted_at IS NULL"
                    ),
                    {"ids": [str(i) for i in scope.material_ids]},
                )
            ).scalar_one()
            if int(found) != len(scope.material_ids):
                raise AppError(404, "not_found", "One of those files was not found.")
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE conversations SET scope = :k, subject_id = :s, "
                        "material_ids = CAST(:m AS uuid[]), updated_at = now() WHERE id = :id "
                        f"RETURNING {_CONVERSATION_COLUMNS}"
                    ),
                    {
                        "k": scope.kind, "s": scope.subject_id,
                        "m": [str(i) for i in scope.material_ids], "id": conversation_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ConversationOut(**row)


# ----------------------------------------------------------------------------------- attachments


class AttachmentOut(BaseModel):
    id: UUID
    filename: str
    kind: str
    size_bytes: int
    status: str
    error: str | None
    char_count: int
    page_count: int | None
    created_at: datetime


_ATTACHMENT_COLUMNS = "id, filename, kind, size_bytes, status, error, char_count, page_count, created_at"


@router.get("/conversations/{conversation_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    conversation_id: UUID, _user: AuthUser, db: UserDbDep
) -> list[AttachmentOut]:
    async with db.session() as session:
        await _get_conversation(session, conversation_id)
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT {_ATTACHMENT_COLUMNS} FROM chat_attachments "
                        "WHERE conversation_id = :c ORDER BY created_at, id"
                    ),
                    {"c": conversation_id},
                )
            )
            .mappings()
            .all()
        )
    return [AttachmentOut(**row) for row in rows]


@router.post(
    "/conversations/{conversation_id}/attachments", status_code=201, response_model=AttachmentOut
)
async def attach_file(
    conversation_id: UUID,
    request: Request,
    user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    queue: QueueDep,
    limiter: LimiterDep,
    file: Annotated[UploadFile, File()],
) -> AttachmentOut:
    """Attach a PDF, Word file or picture of text to this conversation. Its text is read in the
    background; the answers of this conversation can then use it."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_ATTACHMENT_BYTES + 1024 * 1024:
        raise AppError(413, "file_too_large", "That file is larger than the limit for attachments.")
    await limiter.check(f"attach:{user.id}", 30, 3600)

    filename = clean_filename(file.filename or "file")
    data = await _read_limited(file, MAX_ATTACHMENT_BYTES)
    async with db.session() as session:
        await _get_conversation(session, conversation_id)
        existing = int(
            (
                await session.execute(
                    text("SELECT count(*) FROM chat_attachments WHERE conversation_id = :c"),
                    {"c": conversation_id},
                )
            ).scalar_one()
        )
    check = check_attachment(filename, data[:4096], len(data), existing=existing)
    if check.ok and check.extension == "docx" and not is_word_document(data):
        raise rule_error(ChatRuleError("type_mismatch"))
    if not check.ok:
        raise rule_error(ChatRuleError(check.code or "unsupported_type"))

    attachment_id = uuid4()
    # The key never contains the student's file name.
    key = f"chat/{user.id}/{conversation_id}/{attachment_id}.{check.extension}"
    await asyncio.to_thread(storage.put, key, io.BytesIO(data), ATTACHMENT_TYPES[check.extension])
    try:
        async with db.session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO chat_attachments (id, user_id, conversation_id, filename, "
                            "extension, kind, size_bytes, storage_key) VALUES (:id, :u, :c, :f, :e, :k, "
                            f":s, :key) RETURNING {_ATTACHMENT_COLUMNS}"
                        ),
                        {
                            "id": attachment_id, "u": user.id, "c": conversation_id, "f": filename,
                            "e": check.extension, "k": check.kind, "s": len(data), "key": key,
                        },
                    )
                )
                .mappings()
                .one()
            )
    except Exception:
        await asyncio.to_thread(storage.delete, key)
        raise
    try:
        await queue.enqueue_chat_attachment(attachment_id, user.id)
    except Exception:
        logger.warning("Could not enqueue reading of attachment %s", attachment_id, exc_info=True)
        async with db.session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE chat_attachments SET status = 'failed', error = 'queue_unavailable', "
                            f"updated_at = now() WHERE id = :a RETURNING {_ATTACHMENT_COLUMNS}"
                        ),
                        {"a": attachment_id},
                    )
                )
                .mappings()
                .one()
            )
    return AttachmentOut(**row)


@router.delete("/conversations/{conversation_id}/attachments/{attachment_id}", status_code=204)
async def remove_attachment(
    conversation_id: UUID, attachment_id: UUID, _user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    async with db.session() as session:
        key = (
            await session.execute(
                text(
                    "DELETE FROM chat_attachments WHERE id = :a AND conversation_id = :c "
                    "RETURNING storage_key"
                ),
                {"a": attachment_id, "c": conversation_id},
            )
        ).scalar_one_or_none()
    if key is None:
        raise AppError(404, "not_found", "Attachment not found.")
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        logger.warning("Could not delete the stored file of attachment %s", attachment_id, exc_info=True)
    return Response(status_code=204)


# ------------------------------------------------------------------------------------- feedback


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    rating: str
    reason: str | None
    comment: str


@router.put("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def give_feedback(
    message_id: UUID, body: FeedbackIn, user: AuthUser, db: UserDbDep
) -> FeedbackOut:
    """Thumbs up or down on an answer (changing your mind replaces it). Only answers can be rated."""
    try:
        rating, reason, comment = validate_feedback(body.rating, body.reason, body.comment)
    except ChatRuleError as exc:
        raise rule_error(exc) from exc
    async with db.session() as session:
        role = (
            await session.execute(text("SELECT role FROM messages WHERE id = :m"), {"m": message_id})
        ).scalar_one_or_none()
        if role != "assistant":
            raise AppError(404, "not_found", "Answer not found.")
        await session.execute(
            text(
                "INSERT INTO message_feedback (message_id, user_id, rating, reason, comment) "
                "VALUES (:m, :u, :r, :why, :c) ON CONFLICT (message_id, user_id) DO UPDATE SET "
                "rating = :r, reason = :why, comment = :c, updated_at = now()"
            ),
            {"m": message_id, "u": user.id, "r": rating, "why": reason, "c": comment},
        )
    return FeedbackOut(rating=rating, reason=reason, comment=comment)


@router.delete("/messages/{message_id}/feedback", status_code=204)
async def withdraw_feedback(message_id: UUID, user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM message_feedback WHERE message_id = :m AND user_id = :u"),
            {"m": message_id, "u": user.id},
        )
    return Response(status_code=204)


# ------------------------------------------------------------------------------------- versions


class VersionOut(BaseModel):
    id: UUID
    text: str
    created_at: datetime


@router.get("/messages/{message_id}/versions", response_model=list[VersionOut])
async def earlier_versions(message_id: UUID, _user: AuthUser, db: UserDbDep) -> list[VersionOut]:
    """The answers this answer replaced (newest first), when the student asked for it again."""
    async with db.session() as session:
        exists = (
            await session.execute(text("SELECT 1 FROM messages WHERE id = :m"), {"m": message_id})
        ).scalar_one_or_none()
        if exists is None:
            raise AppError(404, "not_found", "Answer not found.")
        rows = (
            (
                await session.execute(
                    text(
                        "WITH RECURSIVE chain AS ("
                        " SELECT p.id, p.replaces_id, p.blocks, p.created_at, 1 AS depth FROM messages p"
                        "  WHERE p.id = (SELECT replaces_id FROM messages WHERE id = :m)"
                        " UNION ALL"
                        " SELECT n.id, n.replaces_id, n.blocks, n.created_at, c.depth + 1 FROM messages n"
                        "  JOIN chain c ON n.id = c.replaces_id WHERE c.depth < 10"
                        ") SELECT id, blocks, created_at FROM chain ORDER BY depth"
                    ),
                    {"m": message_id},
                )
            )
            .mappings()
            .all()
        )
    return [
        VersionOut(id=r["id"], text=_text_of(_as_blocks(r["blocks"])), created_at=r["created_at"])
        for r in rows
    ]
