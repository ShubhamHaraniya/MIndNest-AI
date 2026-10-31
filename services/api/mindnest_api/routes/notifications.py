"""The bell in the top bar: things the student should know about, worked out from their own data.

Nothing is stored for a notification itself. Each one is rebuilt on every request; the table
`notification_reads` only remembers which keys were read. The web app writes the text in the
student's language from `kind` and `params`.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Response
from mindnest_core.plannerlogic import local_today, local_zone
from mindnest_core.quizstore import CARD_DUE_SQL
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep

router = APIRouter(tags=["notifications"])

Severity = Literal["info", "warning", "danger"]
EXAM_WINDOW_DAYS = 7
ASSIGNMENT_WINDOW_DAYS = 3
OVERDUE_WINDOW_DAYS = 14
MAX_ITEMS = 30


class NotificationOut(BaseModel):
    key: str
    kind: Literal[
        "exam_soon", "assignment_due", "assignment_overdue", "revision_due",
        "material_failed", "calendar_reconnect", "tasks_today",
    ]
    severity: Severity
    params: dict[str, Any]
    href: str
    read: bool


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class MarkRead(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=100)


def _exam_bucket(days: int) -> str:
    return "d1" if days <= 1 else "d3" if days <= 3 else "d7"


async def build_notifications(user: AuthUser, session: Any) -> list[dict[str, Any]]:
    """Every current notification (unread or not), most urgent first."""
    today: date = local_today(user.timezone, datetime.now(UTC))
    out: list[dict[str, Any]] = []

    exams = (
        await session.execute(
            text(
                "SELECT e.id, e.title, e.exam_on, s.name AS subject FROM exams e "
                "LEFT JOIN subjects s ON s.id = e.subject_id "
                "WHERE e.exam_on BETWEEN :a AND :b ORDER BY e.exam_on"
            ),
            {"a": today, "b": today + timedelta(days=EXAM_WINDOW_DAYS)},
        )
    ).mappings().all()
    for row in exams:
        days = (row["exam_on"] - today).days
        out.append({
            "key": f"exam:{row['id']}:{_exam_bucket(days)}", "kind": "exam_soon",
            "severity": "danger" if days <= 1 else "warning",
            "params": {"title": row["title"], "days": days, "subject": row["subject"] or ""},
            "href": "/planner", "rank": days,
        })

    assignments = (
        await session.execute(
            text(
                "SELECT id, title, (due_at AT TIME ZONE :tz)::date AS due FROM assignments "
                "WHERE status <> 'done' AND due_at IS NOT NULL "
                "AND (due_at AT TIME ZONE :tz)::date BETWEEN :a AND :b ORDER BY due_at"
            ),
            {"tz": user.timezone, "a": today - timedelta(days=OVERDUE_WINDOW_DAYS),
             "b": today + timedelta(days=ASSIGNMENT_WINDOW_DAYS)},
        )
    ).mappings().all()
    for row in assignments:
        days = (row["due"] - today).days
        overdue = days < 0
        out.append({
            "key": f"assignment:{row['id']}:{'over' if overdue else 'd1' if days <= 1 else 'd3'}",
            "kind": "assignment_overdue" if overdue else "assignment_due",
            "severity": "danger" if overdue or days <= 1 else "warning",
            "params": {"title": row["title"], "days": abs(days)},
            "href": f"/assignments/{row['id']}", "rank": days - 1000 if overdue else days,
        })

    due_cards = (
        await session.execute(
            text(f"SELECT count(*) FROM revision_cards c WHERE {CARD_DUE_SQL}"),
            {"tz": local_zone(user.timezone).key},
        )
    ).scalar_one()
    if due_cards:
        out.append({
            "key": f"revision:{today.isoformat()}", "kind": "revision_due", "severity": "info",
            "params": {"count": int(due_cards)}, "href": "/quizzes", "rank": 50,
        })

    failed = (
        await session.execute(
            text(
                "SELECT id, filename, subject_id FROM materials WHERE deleted_at IS NULL "
                "AND status = 'failed' AND updated_at > now() - interval '7 days' "
                "ORDER BY updated_at DESC LIMIT 5"
            )
        )
    ).mappings().all()
    for row in failed:
        out.append({
            "key": f"material:{row['id']}", "kind": "material_failed", "severity": "warning",
            "params": {"filename": row["filename"]}, "href": f"/subjects/{row['subject_id']}", "rank": 60,
        })

    reconnect = (await session.execute(text("SELECT needs_reconnect FROM google_calendar_links"))).scalar()
    if reconnect:
        out.append({
            "key": "calendar:reconnect", "kind": "calendar_reconnect", "severity": "warning",
            "params": {}, "href": "/calendar", "rank": 55,
        })

    tasks = (
        await session.execute(
            text("SELECT count(*) AS n, COALESCE(sum(minutes), 0) AS m FROM study_tasks "
                 "WHERE planned_for = :d AND status = 'todo'"),
            {"d": today},
        )
    ).mappings().one()
    if tasks["n"]:
        out.append({
            "key": f"tasks:{today.isoformat()}", "kind": "tasks_today", "severity": "info",
            "params": {"count": int(tasks["n"]), "minutes": int(tasks["m"])}, "href": "/planner", "rank": 70,
        })

    out.sort(key=lambda item: item["rank"])
    return out[:MAX_ITEMS]


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(user: AuthUser, db: UserDbDep) -> NotificationsOut:
    async with db.session() as session:
        built = await build_notifications(user, session)
        keys = [item["key"] for item in built]
        read = set()
        if keys:
            read = {
                row[0] for row in (
                    await session.execute(
                        text("SELECT key FROM notification_reads WHERE key = ANY(:keys)"), {"keys": keys}
                    )
                ).all()
            }
    items = [NotificationOut(**{k: v for k, v in item.items() if k != "rank"}, read=item["key"] in read) for item in built]
    return NotificationsOut(unread=sum(not i.read for i in items), items=items)


async def _mark(user: AuthUser, db: UserDbDep, keys: list[str]) -> None:
    async with db.session() as session:
        for key in keys:
            await session.execute(
                text("INSERT INTO notification_reads (user_id, key) VALUES (CAST(:u AS uuid), :k) "
                     "ON CONFLICT (user_id, key) DO NOTHING"),
                {"u": str(user.id), "k": key[:200]},
            )


@router.post("/notifications/read", status_code=204)
async def mark_read(body: MarkRead, user: AuthUser, db: UserDbDep) -> Response:
    await _mark(user, db, body.keys)
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        keys = [item["key"] for item in await build_notifications(user, session)]
    if keys:
        await _mark(user, db, keys)
    return Response(status_code=204)
