"""Assignments, and AI help on them: a breakdown, an outline, feedback on a draft.

Everything is private to the signed-in student (row-level security). The help is written in the
background with the student's own AI key and is built to coach, not to write the assignment.
"""

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from mindnest_core.assignlogic import (
    KINDS,
    MAX_BRIEF_CHARS,
    MAX_DRAFT_CHARS,
    MAX_TITLE,
    needs_draft,
    rubric_total,
)
from mindnest_core.db import as_json
from pydantic import AwareDatetime, BaseModel, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import AuthUser, LimiterDep, QueueDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.llm import PROVIDERS, ProviderId
from mindnest_api.revisions import pin, record_draft
from mindnest_api.routes.quizzes import _has_key

router = APIRouter(tags=["assignments"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE)]
Brief = Annotated[str, StringConstraints(max_length=MAX_BRIEF_CHARS)]
Draft = Annotated[str, StringConstraints(max_length=MAX_DRAFT_CHARS)]
Language = Literal["en", "hi", "gu"]
Kind = Literal["breakdown", "outline", "feedback"]
Status = Literal["todo", "in_progress", "done"]

STALE_MINUTES = 15  # a run still waiting after this long lost its worker; it no longer blocks


# ------------------------------------------------------------------------------ schemas


class AssignmentIn(BaseModel):
    title: Title
    brief: Brief = ""
    subject_id: UUID | None = None
    due_at: AwareDatetime | None = None


class AssignmentPatch(BaseModel):
    title: Title | None = None
    brief: Brief | None = None
    draft: Draft | None = None
    subject_id: UUID | None = None
    due_at: AwareDatetime | None = None
    status: Status | None = None


class RunIn(BaseModel):
    kind: Kind
    language: Language | None = None
    provider: ProviderId | None = None
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class RunOut(BaseModel):
    id: UUID
    kind: str
    language: str
    status: str
    error: str | None
    result: str | None
    sources: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None
    # The snapshot of the draft a feedback run was asked about (see the history tab).
    revision_id: UUID | None = None


class RunBrief(BaseModel):
    kind: str
    id: UUID
    status: str


class AssignmentOut(BaseModel):
    id: UUID
    title: str
    subject_id: UUID | None
    subject_name: str | None
    due_at: datetime | None
    status: str
    has_brief: bool
    has_draft: bool
    updated_at: datetime
    runs: list[RunBrief]
    has_rubric: bool = False
    rubric_points: int = 0
    file_count: int = 0
    word_count: int = 0
    # The latest of: an edit, a saved snapshot, an AI run finishing.
    last_activity_at: datetime | None = None


class CriterionOut(BaseModel):
    id: str
    title: str
    points: int
    descriptor: str


class RubricOut(BaseModel):
    criteria: list[CriterionOut]
    total: int


class FileOut(BaseModel):
    id: UUID  # the material's id: also what `/materials/{id}/download` takes
    filename: str
    mime_type: str | None
    size_bytes: int | None
    status: str
    error: str | None
    created_at: datetime


class AssignmentDetail(AssignmentOut):
    brief: str
    draft: str
    latest_runs: list[RunOut]
    rubric: RubricOut | None = None
    files: list[FileOut] = []
    revision_count: int = 0


# ------------------------------------------------------------------------------ helpers

_LIST_SQL = """
  SELECT a.id, a.title, a.subject_id, s.name AS subject_name, a.due_at, a.status,
         (length(trim(a.brief)) > 0) AS has_brief, (length(trim(a.draft)) > 0) AS has_draft,
         a.updated_at, a.brief, a.draft, a.rubric, (a.rubric IS NOT NULL) AS has_rubric,
         (SELECT count(*) FROM assignment_files f WHERE f.assignment_id = a.id) AS file_count,
         CASE WHEN length(trim(a.draft)) = 0 THEN 0
              ELSE array_length(regexp_split_to_array(trim(a.draft), '\\s+'), 1) END AS word_count,
         GREATEST(
           a.updated_at,
           (SELECT max(r.created_at) FROM assignment_runs r WHERE r.assignment_id = a.id),
           (SELECT max(r.finished_at) FROM assignment_runs r WHERE r.assignment_id = a.id),
           (SELECT max(v.updated_at) FROM assignment_revisions v WHERE v.assignment_id = a.id)
         ) AS last_activity_at,
         COALESCE((
           SELECT json_agg(json_build_object('kind', l.kind, 'id', l.id, 'status', l.status))
           FROM (SELECT DISTINCT ON (r.kind) r.kind, r.id, r.status
                 FROM assignment_runs r WHERE r.assignment_id = a.id
                 ORDER BY r.kind, r.created_at DESC) l
         ), '[]'::json) AS runs
  FROM assignments a LEFT JOIN subjects s ON s.id = a.subject_id
"""


def _rubric_out(raw: Any) -> RubricOut | None:
    data = as_json(raw)
    if not data or not data.get("criteria"):
        return None
    criteria = [CriterionOut(**c) for c in data["criteria"]]
    return RubricOut(criteria=criteria, total=rubric_total([c.model_dump() for c in criteria]))


def _out(row: Any) -> AssignmentOut:
    rubric = _rubric_out(row["rubric"])
    return AssignmentOut(
        id=row["id"], title=row["title"], subject_id=row["subject_id"],
        subject_name=row["subject_name"], due_at=row["due_at"], status=row["status"],
        has_brief=row["has_brief"], has_draft=row["has_draft"], updated_at=row["updated_at"],
        runs=[RunBrief(**r) for r in as_json(row["runs"])],
        has_rubric=rubric is not None, rubric_points=rubric.total if rubric else 0,
        file_count=row["file_count"], word_count=row["word_count"],
        last_activity_at=row["last_activity_at"],
    )


def _run_out(row: Any) -> RunOut:
    return RunOut(
        id=row["id"], kind=row["kind"], language=row["language"], status=row["status"],
        error=row["error"], result=row["result"], sources=as_json(row["sources"]) or [],
        created_at=row["created_at"], finished_at=row["finished_at"],
        revision_id=row["revision_id"],
    )


_RUN_COLUMNS = (
    "id, kind, language, status, error, result, sources, created_at, finished_at, "
    "(config->>'revision_id')::uuid AS revision_id"
)


async def _row(session: AsyncSession, assignment_id: UUID) -> Any:
    row = (
        (await session.execute(text(f"{_LIST_SQL} WHERE a.id = :id"), {"id": assignment_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Assignment not found.")
    return row


async def _check_subject(session: AsyncSession, subject_id: UUID | None) -> None:
    if subject_id is None:
        return
    found = (
        await session.execute(
            text("SELECT 1 FROM subjects WHERE id = :s AND archived_at IS NULL"), {"s": subject_id}
        )
    ).scalar_one_or_none()
    if found is None:
        raise AppError(404, "not_found", "Subject not found.")


async def _has_file_text(session: AsyncSession, assignment_id: UUID) -> bool:
    """True when an attached file has been read, so its text can stand in for a typed brief."""
    found = (
        await session.execute(
            text(
                "SELECT 1 FROM assignment_files f JOIN materials m ON m.id = f.material_id "
                "WHERE f.assignment_id = :a AND m.deleted_at IS NULL AND m.status = 'ready' LIMIT 1"
            ),
            {"a": assignment_id},
        )
    ).scalar_one_or_none()
    return found is not None


async def _detail(session: AsyncSession, assignment_id: UUID) -> AssignmentDetail:
    row = await _row(session, assignment_id)
    runs = (
        (
            await session.execute(
                text(
                    f"SELECT DISTINCT ON (kind) {_RUN_COLUMNS} FROM assignment_runs "
                    "WHERE assignment_id = :a ORDER BY kind, created_at DESC"
                ),
                {"a": assignment_id},
            )
        )
        .mappings()
        .all()
    )
    files = (
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
    revisions = (
        await session.execute(
            text("SELECT count(*) FROM assignment_revisions WHERE assignment_id = :a"),
            {"a": assignment_id},
        )
    ).scalar_one()
    return AssignmentDetail(
        **_out(row).model_dump(), brief=row["brief"], draft=row["draft"],
        latest_runs=[_run_out(r) for r in runs], rubric=_rubric_out(row["rubric"]),
        files=[FileOut(**f) for f in files], revision_count=int(revisions),
    )


# ------------------------------------------------------------------------------ assignments


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(_user: AuthUser, db: UserDbDep) -> list[AssignmentOut]:
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"{_LIST_SQL} ORDER BY (a.status = 'done'), a.due_at NULLS LAST, "
                        "a.created_at DESC LIMIT 300"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [_out(r) for r in rows]


@router.post("/assignments", status_code=201, response_model=AssignmentDetail)
async def create_assignment(
    body: AssignmentIn, user: AuthUser, db: UserDbDep, limiter: LimiterDep
) -> AssignmentDetail:
    await limiter.check(f"assignment-create:{user.id}", 30, 3600)
    async with db.session() as session:
        await _check_subject(session, body.subject_id)
        assignment_id = (
            await session.execute(
                text(
                    "INSERT INTO assignments (user_id, subject_id, title, brief, due_at) "
                    "VALUES (:u, :s, :t, :b, :d) RETURNING id"
                ),
                {"u": user.id, "s": body.subject_id, "t": body.title, "b": body.brief, "d": body.due_at},
            )
        ).scalar_one()
        return await _detail(session, assignment_id)


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail)
async def get_assignment(assignment_id: UUID, _user: AuthUser, db: UserDbDep) -> AssignmentDetail:
    async with db.session() as session:
        return await _detail(session, assignment_id)


@router.patch("/assignments/{assignment_id}", response_model=AssignmentDetail)
async def update_assignment(
    assignment_id: UUID, body: AssignmentPatch, user: AuthUser, db: UserDbDep
) -> AssignmentDetail:
    sent = body.model_fields_set
    # title, brief, draft and status cannot be cleared to null; subject_id and due_at can.
    for name in ("title", "brief", "draft", "status"):
        if name in sent and getattr(body, name) is None:
            raise AppError(422, "validation_error", f"{name} cannot be empty.")
    changes: dict[str, Any] = {name: getattr(body, name) for name in sent}
    async with db.session() as session:
        before = await _row(session, assignment_id)
        if "subject_id" in changes:
            await _check_subject(session, changes["subject_id"])
        if changes:
            sets = ", ".join(f"{name} = :{name}" for name in changes)
            await session.execute(
                text(f"UPDATE assignments SET {sets}, updated_at = now() WHERE id = :id"),
                {**changes, "id": assignment_id},
            )
        if "draft" in changes:
            await record_draft(
                session, user.id, assignment_id, before["draft"], changes["draft"], before["updated_at"]
            )
        return await _detail(session, assignment_id)


@router.delete("/assignments/{assignment_id}", status_code=204)
async def delete_assignment(assignment_id: UUID, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        result = await session.execute(
            text("DELETE FROM assignments WHERE id = :id"), {"id": assignment_id}
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Assignment not found.")
    return Response(status_code=204)


# ------------------------------------------------------------------------------ runs


@router.post("/assignments/{assignment_id}/runs", status_code=201, response_model=RunOut)
async def start_run(
    assignment_id: UUID, body: RunIn, user: AuthUser, db: UserDbDep, queue: QueueDep,
    limiter: LimiterDep,
) -> RunOut:
    await limiter.check(f"assignment-run:{user.id}", 20, 3600)
    assert body.kind in KINDS
    async with db.session() as session:
        row = await _row(session, assignment_id)
        if needs_draft(body.kind) and not row["has_draft"]:
            raise AppError(409, "draft_required", "Paste your draft first.")
        if not needs_draft(body.kind) and not row["has_brief"] and not await _has_file_text(
            session, assignment_id
        ):
            raise AppError(409, "brief_required", "Add the assignment brief first.")
        key = await _has_key(session, body.provider)
        if key is None:
            raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")
        provider, saved_model = key
        await session.execute(
            text(
                "UPDATE assignment_runs SET status = 'failed', error = 'timeout', finished_at = now() "
                "WHERE assignment_id = :a AND status IN ('queued', 'running') "
                "AND created_at < now() - make_interval(mins => :m)"
            ),
            {"a": assignment_id, "m": STALE_MINUTES},
        )
        busy = (
            await session.execute(
                text(
                    "SELECT 1 FROM assignment_runs WHERE assignment_id = :a AND kind = :k "
                    "AND status IN ('queued', 'running')"
                ),
                {"a": assignment_id, "k": body.kind},
            )
        ).scalar_one_or_none()
        if busy is not None:
            raise AppError(409, "run_in_progress", "This is already being written.")
        language = body.language or user.answer_language or user.ui_language
        config: dict[str, Any] = {
            "provider": provider,
            "model": body.model or saved_model or PROVIDERS[provider].default_model,
        }
        if needs_draft(body.kind):
            # The draft the feedback is about is pinned in history, so it can be read again later.
            pinned = await pin(session, user.id, assignment_id, row["draft"], source="feedback")
            if pinned is not None:
                config["revision_id"] = str(pinned)
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO assignment_runs (assignment_id, user_id, kind, language, config) "
                    "VALUES (:a, :u, :k, :l, CAST(:c AS jsonb)) RETURNING id"
                ),
                {"a": assignment_id, "u": user.id, "k": body.kind, "l": language, "c": json.dumps(config)},
            )
        ).scalar_one()
        created = (
            (
                await session.execute(
                    text(f"SELECT {_RUN_COLUMNS} FROM assignment_runs WHERE id = :r"), {"r": run_id}
                )
            )
            .mappings()
            .one()
        )
        out = _run_out(created)
    # Enqueued after the commit, so the worker can always see the row.
    await queue.enqueue_assignment_run(run_id, user.id)
    return out


@router.get("/assignments/{assignment_id}/runs/{run_id}", response_model=RunOut)
async def get_run(assignment_id: UUID, run_id: UUID, _user: AuthUser, db: UserDbDep) -> RunOut:
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT {_RUN_COLUMNS} FROM assignment_runs "
                        "WHERE id = :r AND assignment_id = :a"
                    ),
                    {"r": run_id, "a": assignment_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise AppError(404, "not_found", "Not found.")
    return _run_out(row)

