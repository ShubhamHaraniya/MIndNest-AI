"""Reading a file the student attached to a chat.

The text is stored on the attachment row and given to the AI as part of that conversation. It is
not added to the student's materials, so it is never searched from other chats and never shown in
a course. A scanned PDF page or a photo is read with OCR (only text in the picture is understood).
"""

import asyncio
import logging
from uuid import UUID

from mindnest_core.chatlogic import MAX_ATTACHMENT_TEXT
from mindnest_core.db import user_session
from mindnest_core.filetypes import looks_like
from mindnest_core.redact import redact
from mindnest_core.settings import Settings
from mindnest_core.storage import ObjectStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mindnest_worker.chunking import Segment
from mindnest_worker.parsing import IngestError, parse_document, run_ocr

logger = logging.getLogger("mindnest.chatfiles")

type SessionFactory = async_sessionmaker[AsyncSession]

# Scanned pages are slow to read; a chat attachment is a quick look, not a whole textbook.
MAX_CHAT_OCR_PAGES = 15


def join_segments(segments: list[Segment], limit: int = MAX_ATTACHMENT_TEXT) -> tuple[str, int | None]:
    """The text of the file in reading order (pages marked), cut to `limit` characters, and the
    highest page number seen."""
    parts: list[str] = []
    used = 0
    pages = [s.page for s in segments if s.page is not None]
    for segment in segments:
        body = segment.text.strip()
        if not body:
            continue
        label = f"[page {segment.page}]\n" if segment.page is not None else ""
        piece = f"{label}{body}"
        room = limit - used
        if room <= 0:
            break
        piece = piece[:room]
        parts.append(piece)
        used += len(piece) + 2
    return "\n\n".join(parts), (max(pages) if pages else None)


async def read_attachment(
    attachment_id: UUID, owner_id: UUID, *, factory: SessionFactory, storage: ObjectStorage,
    settings: Settings,
) -> None:
    """Read one attachment. Never raises: the outcome is recorded on the row. Safe to deliver twice."""
    async with user_session(factory, owner_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE chat_attachments SET status = 'processing', updated_at = now() "
                        "WHERE id = :a AND status IN ('uploaded', 'processing') "
                        "RETURNING storage_key, extension"
                    ),
                    {"a": attachment_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return  # deleted, or already read

    try:
        data = await asyncio.to_thread(storage.get_bytes, row["storage_key"])
        extension = str(row["extension"])
        if not data or not looks_like(extension, data[:4096]):
            raise IngestError("unreadable_file")
        parsed = await asyncio.to_thread(parse_document, extension, data)
        segments: list[Segment] = list(parsed.segments)
        if parsed.needs_ocr:
            extra = await asyncio.to_thread(
                run_ocr, extension, data, parsed, settings.ocr_languages,
                min(settings.max_ocr_pages, MAX_CHAT_OCR_PAGES),
            )
            segments.extend(extra)
            segments.sort(key=lambda s: (s.page is None, s.page or 0))
        content, pages = join_segments(segments)
        if not content.strip():
            raise IngestError("no_text")
        await _finish(factory, owner_id, attachment_id, "ready", content=content, pages=pages)
    except IngestError as exc:
        await _finish(factory, owner_id, attachment_id, "failed", error=exc.code)
    except Exception as exc:
        logger.error("Reading attachment %s failed: %s", attachment_id, redact(f"{type(exc).__name__}: {exc}"))
        await _finish(factory, owner_id, attachment_id, "failed", error="internal")


async def _finish(
    factory: SessionFactory, owner_id: UUID, attachment_id: UUID, status: str, *,
    content: str = "", pages: int | None = None, error: str | None = None,
) -> None:
    try:
        async with user_session(factory, owner_id) as session:
            await session.execute(
                text(
                    "UPDATE chat_attachments SET status = :s, error = :e, text_content = :t, "
                    "char_count = :n, page_count = :p, updated_at = now() WHERE id = :a"
                ),
                {"s": status, "e": error, "t": content, "n": len(content), "p": pages, "a": attachment_id},
            )
    except Exception:
        logger.exception("Could not record the result for attachment %s", attachment_id)
