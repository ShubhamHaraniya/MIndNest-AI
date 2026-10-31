"""The history of an assignment's draft: snapshots taken as the student saves.

Saving the draft keeps a snapshot, but not one per keystroke: an automatic snapshot that is still
recent is updated in place (see `assignlogic.revision_action`), so a long writing session leaves a
handful of rows, not hundreds. A student can pin the current draft with a note, and asking for
feedback and restoring an older version pin it too. Those are never folded into or pruned.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mindnest_core.assignlogic import MAX_AUTO_REVISIONS, revision_action, word_count
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LATEST = (
    "SELECT id, source, body, created_at, clock_timestamp() AS db_now FROM assignment_revisions "
    "WHERE assignment_id = :a ORDER BY created_at DESC, id LIMIT 1"
)

_INSERT = (
    "INSERT INTO assignment_revisions (assignment_id, user_id, body, word_count, source, note, "
    "created_at, updated_at) VALUES (:a, :u, :b, :w, :s, :n, COALESCE(:at, clock_timestamp()), "
    "COALESCE(:at, clock_timestamp())) RETURNING id"
)


async def _latest(session: AsyncSession, assignment_id: UUID) -> Any:
    return (await session.execute(text(_LATEST), {"a": assignment_id})).mappings().first()


async def _insert(
    session: AsyncSession, user_id: UUID, assignment_id: UUID, body: str, source: str, note: str,
    at: Any = None,
) -> UUID:
    new_id = (
        await session.execute(
            text(_INSERT),
            {"a": assignment_id, "u": user_id, "b": body, "w": word_count(body), "s": source,
             "n": note, "at": at},
        )
    ).scalar_one()
    assert isinstance(new_id, UUID)
    return new_id


async def _prune(session: AsyncSession, assignment_id: UUID) -> None:
    """Keep the newest MAX_AUTO_REVISIONS automatic snapshots; named ones are never removed."""
    await session.execute(
        text(
            "DELETE FROM assignment_revisions WHERE id IN ("
            "SELECT id FROM assignment_revisions WHERE assignment_id = :a "
            "AND source IN ('auto', 'baseline') ORDER BY created_at DESC OFFSET :keep)"
        ),
        {"a": assignment_id, "keep": MAX_AUTO_REVISIONS},
    )


async def record_draft(
    session: AsyncSession, user_id: UUID, assignment_id: UUID, old: str, new: str, old_saved_at: Any
) -> UUID | None:
    """The draft was just saved as `new` (it was `old`). Keep or fold the snapshot as the rules say."""
    if old == new:
        return None
    latest = await _latest(session, assignment_id)
    if latest is None and old.strip():
        # The first time history is used for a draft that already existed, keep what was there.
        await _insert(session, user_id, assignment_id, old, "baseline", "", old_saved_at)
        latest = await _latest(session, assignment_id)
    action = revision_action(
        latest["source"] if latest else None,
        latest["body"] if latest else None,
        latest["created_at"] if latest else None,
        new,
        latest["db_now"] if latest else datetime.now(UTC),
    )
    if action == "skip":
        return None
    if action == "update":
        await session.execute(
            text(
                "UPDATE assignment_revisions SET body = :b, word_count = :w, "
                "updated_at = clock_timestamp() WHERE id = :id"
            ),
            {"b": new, "w": word_count(new), "id": latest["id"]},
        )
        return latest["id"]  # type: ignore[no-any-return]
    created = await _insert(session, user_id, assignment_id, new, "auto", "")
    await _prune(session, assignment_id)
    return created


async def pin(
    session: AsyncSession, user_id: UUID, assignment_id: UUID, body: str, *, source: str, note: str = ""
) -> UUID | None:
    """Keep `body` (the draft as it is now) in history as a snapshot that will not be folded into
    another. If it is already the latest snapshot, that one is promoted rather than copied.
    None means there was nothing worth keeping (an empty draft)."""
    latest = await _latest(session, assignment_id)
    if latest is not None and latest["body"] == body:
        promote = latest["source"] in ("auto", "baseline")
        await session.execute(
            text(
                "UPDATE assignment_revisions SET source = CASE WHEN :p THEN :s ELSE source END, "
                "note = CASE WHEN :n <> '' THEN :n ELSE note END WHERE id = :id"
            ),
            {"p": promote, "s": source, "n": note, "id": latest["id"]},
        )
        return latest["id"]  # type: ignore[no-any-return]
    if not body.strip():
        return None
    return await _insert(session, user_id, assignment_id, body, source, note)

