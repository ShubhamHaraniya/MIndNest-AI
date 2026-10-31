"""The admin screens: how the service is doing, who is using it, and what has been reported.

Every route needs an admin account, and every query goes through a database function that checks
that again. Admins see counts, names and e-mail addresses (to help with accounts) and the names and
report reasons of reported files. They cannot read any student's materials, chats, quizzes,
drafts or keys, and every change they make is written to an audit log.
"""

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mindnest_api.deps import AuthUser, CurrentUser, StorageDep, UserDbDep
from mindnest_api.errors import AppError

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("mindnest.admin")

Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


async def require_admin(user: AuthUser, db: UserDbDep) -> CurrentUser:
    async with db.session() as session:
        allowed = (await session.execute(text("SELECT app_is_admin()"))).scalar_one()
    if not allowed:
        raise AppError(403, "forbidden", "This page is for administrators.")
    return user


AdminUser = Annotated[CurrentUser, Depends(require_admin)]


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


# ------------------------------------------------------------------------------ schemas


class SeriesPoint(BaseModel):
    day: date
    signups: int
    active_users: int


class OverviewOut(BaseModel):
    totals: dict[str, int]
    series: list[SeriesPoint]


class AdminUserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    status: Literal["active", "suspended"]
    email_verified: bool
    is_admin: bool
    has_google: bool
    created_at: datetime
    last_seen_at: datetime | None
    subjects: int
    materials: int
    storage_bytes: int
    messages_30d: int


class UsersOut(BaseModel):
    items: list[AdminUserOut]
    total: int


class StatusIn(BaseModel):
    status: Literal["active", "suspended"]
    reason: Reason = ""


class StatusOut(BaseModel):
    status: Literal["active", "suspended"]


class ReportedItemOut(BaseModel):
    item_id: UUID
    group_id: UUID
    group_name: str
    filename: str
    kind: str
    size_bytes: int | None
    status: Literal["active", "hidden"]
    shared_by_name: str
    shared_by_email: str
    reports: int
    last_report_at: datetime | None
    reasons: dict[str, int]
    notes: list[str]
    created_at: datetime


class RemoveIn(BaseModel):
    reason: Reason = ""


class SecurityRow(BaseModel):
    kind: str
    events: int
    students: int


class AuditRow(BaseModel):
    id: UUID
    admin_name: str | None
    action: str
    target_email: str | None
    detail: dict[str, Any]
    created_at: datetime


# ------------------------------------------------------------------------------ routes


@router.get("/overview", response_model=OverviewOut)
async def overview(_admin: AdminUser, db: UserDbDep, days: Annotated[int, Query(ge=7, le=90)] = 30) -> OverviewOut:
    async with db.session() as session:
        totals = _json((await session.execute(text("SELECT app_admin_overview()"))).scalar_one())
        rows = (await session.execute(text("SELECT * FROM app_admin_signups(:d)"), {"d": days})).mappings().all()
    return OverviewOut(totals={k: int(v) for k, v in totals.items()}, series=[SeriesPoint(**r) for r in rows])


def _like(query: str) -> str:
    """Search text with the LIKE wildcards made literal."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/users", response_model=UsersOut)
async def users(
    _admin: AdminUser,
    db: UserDbDep,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> UsersOut:
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT * FROM app_admin_users(:q, :l, :o)"),
                    {"q": _like(q.strip()), "l": limit, "o": offset},
                )
            )
            .mappings()
            .all()
        )
    total = int(rows[0]["total"]) if rows else 0
    return UsersOut(items=[AdminUserOut(**{k: v for k, v in r.items() if k != "total"}) for r in rows], total=total)


@router.post("/users/{user_id}/status", response_model=StatusOut)
async def set_status(user_id: UUID, body: StatusIn, _admin: AdminUser, db: UserDbDep) -> StatusOut:
    try:
        async with db.session() as session:
            result = (
                await session.execute(
                    text("SELECT app_admin_set_status(:u, :s, :r)"),
                    {"u": user_id, "s": body.status, "r": body.reason},
                )
            ).scalar_one()
    except DBAPIError as exc:
        if "admin account" in str(exc):
            raise AppError(409, "admin_account", "Admin accounts cannot be changed here.") from exc
        raise
    if result is None:
        raise AppError(404, "not_found", "No such account.")
    return StatusOut(status=result)


@router.get("/reports", response_model=list[ReportedItemOut])
async def reports(_admin: AdminUser, db: UserDbDep) -> list[ReportedItemOut]:
    async with db.session() as session:
        rows = (await session.execute(text("SELECT * FROM app_admin_reports()"))).mappings().all()
    return [
        ReportedItemOut(**{**r, "reasons": _json(r["reasons"]), "notes": _json(r["notes"])}) for r in rows
    ]


@router.post("/reports/{item_id}/remove", status_code=204)
async def remove_reported(
    item_id: UUID, body: RemoveIn, _admin: AdminUser, db: UserDbDep, storage: StorageDep
) -> Response:
    async with db.session() as session:
        key = (
            await session.execute(
                text("SELECT app_admin_remove_item(:i, :r)"), {"i": item_id, "r": body.reason}
            )
        ).scalar_one()
    if key is None:
        raise AppError(404, "not_found", "That file no longer exists.")
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        log.warning("could not delete stored file %s", key, exc_info=True)
    return Response(status_code=204)


@router.post("/reports/{item_id}/dismiss", status_code=204)
async def dismiss_reports(item_id: UUID, _admin: AdminUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        found = (await session.execute(text("SELECT app_admin_dismiss_reports(:i)"), {"i": item_id})).scalar_one()
    if not found:
        raise AppError(404, "not_found", "That file no longer exists.")
    return Response(status_code=204)


# ------------------------------------------------------------------ materials library


class LibraryQueueRow(BaseModel):
    id: UUID
    title: str
    filename: str
    doc_type: str
    visibility: Literal["private", "institution", "public"]
    status: Literal["draft", "pending_review", "published", "rejected", "held", "taken_down"]
    rights: str
    institution: str
    author: str
    owner_name: str
    reports: int
    reasons: list[str]
    notes: list[str]
    # Copies students added to their own courses (a takedown pulls these out of the retrieval index).
    imports: int
    created_at: datetime


class LibraryDecisionIn(BaseModel):
    note: Reason = ""


@router.get("/library", response_model=list[LibraryQueueRow])
async def library_queue(_admin: AdminUser, db: UserDbDep) -> list[LibraryQueueRow]:
    """Public items waiting for review, items held back by reports, and anything with a report."""
    async with db.session() as session:
        rows = (await session.execute(text("SELECT * FROM app_admin_library_queue()"))).mappings().all()
    return [
        LibraryQueueRow(**{**r, "reasons": _json(r["reasons"]), "notes": _json(r["notes"])}) for r in rows
    ]


@router.post("/library/{item_id}/{action}", status_code=204)
async def library_decide(
    item_id: UUID,
    action: Literal["approve", "reject", "takedown"],
    body: LibraryDecisionIn,
    _admin: AdminUser,
    db: UserDbDep,
    storage: StorageDep,
) -> Response:
    async with db.session() as session:
        keys = (
            await session.execute(
                text("SELECT app_admin_library_decide(:i, :a, :n)"),
                {"i": item_id, "a": action, "n": body.note},
            )
        ).scalar_one()
    if keys is None:
        raise AppError(404, "not_found", "That file no longer exists.")
    for key in keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            log.warning("could not delete stored file %s", key, exc_info=True)
    return Response(status_code=204)


@router.get("/security", response_model=list[SecurityRow])
async def security(
    _admin: AdminUser, db: UserDbDep, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> list[SecurityRow]:
    async with db.session() as session:
        rows = (await session.execute(text("SELECT * FROM app_admin_security(:d)"), {"d": days})).mappings().all()
    return [SecurityRow(**r) for r in rows]


@router.get("/audit", response_model=list[AuditRow])
async def audit(_admin: AdminUser, db: UserDbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[AuditRow]:
    async with db.session() as session:
        rows = (await session.execute(text("SELECT * FROM app_admin_audit(:l)"), {"l": limit})).mappings().all()
    return [AuditRow(**{**r, "detail": _json(r["detail"])}) for r in rows]
