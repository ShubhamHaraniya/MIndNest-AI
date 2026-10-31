"""The workspace around an assignment: its rubric, attached files and draft history.

Everything is private to the signed-in student (row-level security); another student's assignment,
file or snapshot is always "not found". Files are ordinary materials (kind "assignment") that are
linked to the assignment, so they are stored, read and searchable like every other upload.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Request, Response, UploadFile
from mindnest_core.assignlogic import (
    MAX_CRITERIA,
    MAX_CRITERION_POINTS,
    MAX_CRITERION_TITLE,
    MAX_DESCRIPTOR,
    MAX_FILES,
)
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, StorageDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.revisions import pin
from mindnest_api.routes.assignments import (
    AssignmentDetail,
    FileOut,
    RubricOut,
    RunOut,
    _detail,
    _RUN_COLUMNS,
    _row,
    _rubric_out,
    _run_out,
)
from mindnest_api.routes.materials import upload_material

router = APIRouter(tags=["assignments"])
logger = logging.getLogger("mindnest.assignments")

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
RevisionSource = Literal["auto", "manual", "restore", "feedback", "baseline"]


# ------------------------------------------------------------------------------ rubric


class CriterionIn(BaseModel):
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")] | None = None
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CRITERION_TITLE)
    ]
    points: int = Field(ge=0, le=MAX_CRITERION_POINTS)
    descriptor: Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_DESCRIPTOR)] = ""


class RubricIn(BaseModel):
    """An empty list removes the rubric."""

    criteria: list[CriterionIn] = Field(max_length=MAX_CRITERIA)

    @model_validator(mode="after")
    def _unique_ids(self) -> "RubricIn":
        given = [c.id for c in self.criteria if c.id]
        if len(given) != len(set(given)):
            raise ValueError("criterion ids must be unique")
        return self


@router.put("/assignments/{assignment_id}/rubric", response_model=RubricOut | None)
async def put_rubric(
    assignment_id: UUID, body: RubricIn, _user: AuthUser, db: UserDbDep
) -> RubricOut | None:
    async with db.session() as session:
        await _row(session, assignment_id)
        taken = {c.id for c in body.criteria if c.id}
        criteria: list[dict[str, Any]] = []
        for criterion in body.criteria:
            cid = criterion.id
            while not cid or (cid in taken and cid != criterion.id):
                cid = uuid4().hex[:8]
            taken.add(cid)
            criteria.append(
                {"id": cid, "title": criterion.title, "points": criterion.points,
                 "descriptor": criterion.descriptor}
            )
        await session.execute(
            text(
                "UPDATE assignments SET rubric = CAST(:r AS jsonb), updated_at = now() WHERE id = :id"
            ),
            {"r": json.dumps({"criteria": criteria}) if criteria else None, "id": assignment_id},
        )
        row = await _row(session, assignment_id)
    return _rubric_out(row["rubric"])


# ------------------------------------------------------------------------------ files


async def _files(session: AsyncSession, assignment_id: UUID) -> list[FileOut]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT m.id, m.filename, m.mime_type, m.size_bytes, m.status, m.error, f.created_at "
                    "FROM assignment_files f JOIN materials m ON m.id = f.material_id "
                    "WHERE f.assignment_id = :a AND m.deleted_at IS NULL ORDER BY f.created_at, m.id"
                ),
                {"a": assignment_id},
            )
        )
        .mappings()
        .all()
    )
    return [FileOut(**r) for r in rows]


@router.get("/assignments/{assignment_id}/files", response_model=list[FileOut])
async def list_files(assignment_id: UUID, _user: AuthUser, db: UserDbDep) -> list[FileOut]:
    async with db.session() as session:
        await _row(session, assignment_id)
        return await _files(session, assignment_id)


@router.post("/assignments/{assignment_id}/files", status_code=201, response_model=FileOut)
async def attach_file(
    assignment_id: UUID,
    request: Request,
    user: AuthUser,
    db: UserDbDep,
    storage: StorageDep,
    queue: QueueDep,
    limiter: LimiterDep,
    file: Annotated[UploadFile, File()],
) -> FileOut:
    """Upload a file (the question paper, a handout, a marking guide) onto this assignment. It is
    stored in the assignment's course like any other upload and read in the background."""
    async with db.session() as session:
        row = await _row(session, assignment_id)
        if row["subject_id"] is None:
            raise AppError(409, "subject_required", "Choose the assignment's course before adding files.")
        count = (
            await session.execute(
                text("SELECT count(*) FROM assignment_files WHERE assignment_id = :a"),
                {"a": assignment_id},
            )
        ).scalar_one()
        if count >= MAX_FILES:
            raise AppError(409, "too_many_files", f"An assignment can have at most {MAX_FILES} files.")
        subject_id = row["subject_id"]
    material = await upload_material(
        subject_id, request, user, db, storage, queue, limiter, file, "assignment", None
    )
    try:
        async with db.session() as session:
            await session.execute(
                text(
                    "INSERT INTO assignment_files (assignment_id, material_id, user_id) "
                    "VALUES (:a, :m, :u)"
                ),
                {"a": assignment_id, "m": material.id, "u": user.id},
            )
            await session.execute(
                text("UPDATE assignments SET updated_at = now() WHERE id = :a"), {"a": assignment_id}
            )
    except Exception:
        await _discard_material(db, storage, material.id)
        raise
    return FileOut(
        id=material.id, filename=material.filename, mime_type=material.mime_type,
        size_bytes=material.size_bytes, status=material.status, error=material.error,
        created_at=material.created_at,
    )


async def _discard_material(db: UserDbDep, storage: StorageDep, material_id: UUID) -> None:
    async with db.session() as session:
        key = (
            await session.execute(
                text("DELETE FROM materials WHERE id = :id RETURNING storage_key"), {"id": material_id}
            )
        ).scalar_one_or_none()
    if key is not None:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            logger.warning("Could not delete stored file %s", key, exc_info=True)


@router.delete("/assignments/{assignment_id}/files/{material_id}", status_code=204)
async def remove_file(
    assignment_id: UUID, material_id: UUID, _user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    """Take a file off the assignment. The file itself is deleted too: it was uploaded for this."""
    async with db.session() as session:
        await _row(session, assignment_id)
        linked = (
            await session.execute(
                text("SELECT 1 FROM assignment_files WHERE assignment_id = :a AND material_id = :m"),
                {"a": assignment_id, "m": material_id},
            )
        ).scalar_one_or_none()
        if linked is None:
            raise AppError(404, "not_found", "File not found.")
        await session.execute(
            text("UPDATE assignments SET updated_at = now() WHERE id = :a"), {"a": assignment_id}
        )
    await _discard_material(db, storage, material_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------------ history


class RevisionBrief(BaseModel):
    id: UUID
    source: RevisionSource
    note: str
    word_count: int
    created_at: datetime
    updated_at: datetime


class RevisionOut(RevisionBrief):
    body: str


class RevisionIn(BaseModel):
    note: Note = ""


_BRIEF_COLUMNS = "id, source, note, word_count, created_at, updated_at"


@router.get("/assignments/{assignment_id}/revisions", response_model=list[RevisionBrief])
async def list_revisions(assignment_id: UUID, _user: AuthUser, db: UserDbDep) -> list[RevisionBrief]:
    async with db.session() as session:
        await _row(session, assignment_id)
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT {_BRIEF_COLUMNS} FROM assignment_revisions WHERE assignment_id = :a "
                        "ORDER BY created_at DESC, id LIMIT 300"
                    ),
                    {"a": assignment_id},
                )
            )
            .mappings()
            .all()
        )
    return [RevisionBrief(**r) for r in rows]


async def _revision(session: AsyncSession, assignment_id: UUID, revision_id: UUID) -> Any:
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {_BRIEF_COLUMNS}, body FROM assignment_revisions "
                    "WHERE id = :r AND assignment_id = :a"
                ),
                {"r": revision_id, "a": assignment_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Revision not found.")
    return row


@router.post("/assignments/{assignment_id}/revisions", status_code=201, response_model=RevisionOut)
async def save_revision(
    assignment_id: UUID, body: RevisionIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> RevisionOut:
    """Pin the draft as it is saved now, with an optional note ("first full draft")."""
    await limiter.check(f"assignment-revision:{user.id}", 120, 3600)
    async with db.session() as session:
        row = await _row(session, assignment_id)
        pinned = await pin(session, user.id, assignment_id, row["draft"], source="manual", note=body.note)
        if pinned is None:
            raise AppError(409, "draft_required", "Write something in the draft first.")
        return RevisionOut(**await _revision(session, assignment_id, pinned))


@router.get("/assignments/{assignment_id}/revisions/{revision_id}", response_model=RevisionOut)
async def get_revision(
    assignment_id: UUID, revision_id: UUID, _user: AuthUser, db: UserDbDep
) -> RevisionOut:
    async with db.session() as session:
        return RevisionOut(**await _revision(session, assignment_id, revision_id))


@router.post(
    "/assignments/{assignment_id}/revisions/{revision_id}/restore", response_model=AssignmentDetail
)
async def restore_revision(
    assignment_id: UUID, revision_id: UUID, user: AuthUser, db: UserDbDep
) -> AssignmentDetail:
    """Make an older snapshot the draft again. What the draft was is kept first, so a restore
    can always be undone."""
    async with db.session() as session:
        current = await _row(session, assignment_id)
        wanted = await _revision(session, assignment_id, revision_id)
        if current["draft"] != wanted["body"]:
            await pin(session, user.id, assignment_id, current["draft"], source="manual")
            await session.execute(
                text("UPDATE assignments SET draft = :d, updated_at = now() WHERE id = :id"),
                {"d": wanted["body"], "id": assignment_id},
            )
            await pin(session, user.id, assignment_id, wanted["body"], source="restore")
        return await _detail(session, assignment_id)


# ------------------------------------------------------------------------------ AI runs


@router.get("/assignments/{assignment_id}/runs", response_model=list[RunOut])
async def list_runs(assignment_id: UUID, _user: AuthUser, db: UserDbDep) -> list[RunOut]:
    """Every piece of AI help on this assignment, newest first (the detail page only carries the
    latest of each kind)."""
    async with db.session() as session:
        await _row(session, assignment_id)
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT {_RUN_COLUMNS} FROM assignment_runs WHERE assignment_id = :a "
                        "ORDER BY created_at DESC LIMIT 50"
                    ),
                    {"a": assignment_id},
                )
            )
            .mappings()
            .all()
        )
    return [_run_out(r) for r in rows]
