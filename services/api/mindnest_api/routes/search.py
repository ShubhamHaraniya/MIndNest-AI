"""Search across everything a student owns, for the search box and command palette (Ctrl/Cmd+K)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep

router = APIRouter(tags=["search"])

PER_GROUP = 5
MIN_LENGTH = 2


class Hit(BaseModel):
    id: UUID
    title: str
    detail: str | None = None
    href: str


class SearchOut(BaseModel):
    query: str
    subjects: list[Hit]
    materials: list[Hit]
    quizzes: list[Hit]
    assignments: list[Hit]
    conversations: list[Hit]
    exams: list[Hit]


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search", response_model=SearchOut)
async def search(
    _user: AuthUser, db: UserDbDep, q: Annotated[str, Query(max_length=100)] = ""
) -> SearchOut:
    term = q.strip()
    empty = SearchOut(query=term, subjects=[], materials=[], quizzes=[], assignments=[], conversations=[], exams=[])
    if len(term) < MIN_LENGTH:
        return empty
    params: dict[str, Any] = {"q": _like(term), "n": PER_GROUP}
    async with db.session() as session:

        async def rows(sql: str) -> list[Any]:
            return list((await session.execute(text(sql), params)).mappings().all())

        subjects = await rows(
            r"SELECT id, name, course_code FROM subjects WHERE archived_at IS NULL "
            r"AND (name ILIKE :q ESCAPE '\' OR course_code ILIKE :q ESCAPE '\') ORDER BY updated_at DESC LIMIT :n"
        )
        materials = await rows(
            r"SELECT m.id, m.filename, m.subject_id, s.name AS subject FROM materials m "
            r"LEFT JOIN subjects s ON s.id = m.subject_id WHERE m.deleted_at IS NULL "
            r"AND m.filename ILIKE :q ESCAPE '\' ORDER BY m.created_at DESC LIMIT :n"
        )
        quizzes = await rows(
            r"SELECT z.id, z.title, s.name AS subject FROM quizzes z LEFT JOIN subjects s ON s.id = z.subject_id "
            r"WHERE z.title ILIKE :q ESCAPE '\' ORDER BY z.created_at DESC LIMIT :n"
        )
        assignments = await rows(
            r"SELECT a.id, a.title, s.name AS subject FROM assignments a LEFT JOIN subjects s ON s.id = a.subject_id "
            r"WHERE a.title ILIKE :q ESCAPE '\' ORDER BY a.updated_at DESC LIMIT :n"
        )
        conversations = await rows(
            r"SELECT id, title FROM conversations WHERE title ILIKE :q ESCAPE '\' ORDER BY updated_at DESC LIMIT :n"
        )
        exams = await rows(
            r"SELECT e.id, e.title, e.exam_on, s.name AS subject FROM exams e LEFT JOIN subjects s ON s.id = e.subject_id "
            r"WHERE e.title ILIKE :q ESCAPE '\' ORDER BY e.exam_on DESC LIMIT :n"
        )
    return SearchOut(
        query=term,
        subjects=[Hit(id=r["id"], title=r["name"], detail=r["course_code"], href=f"/subjects/{r['id']}") for r in subjects],
        materials=[
            Hit(id=r["id"], title=r["filename"], detail=r["subject"],
                href=f"/subjects/{r['subject_id']}" if r["subject_id"] else "/library")
            for r in materials
        ],
        quizzes=[Hit(id=r["id"], title=r["title"], detail=r["subject"], href=f"/quizzes/{r['id']}") for r in quizzes],
        assignments=[Hit(id=r["id"], title=r["title"], detail=r["subject"], href=f"/assignments/{r['id']}") for r in assignments],
        conversations=[Hit(id=r["id"], title=r["title"], href=f"/chat?c={r['id']}") for r in conversations],
        exams=[Hit(id=r["id"], title=r["title"], detail=r["subject"] or r["exam_on"].isoformat(), href="/planner") for r in exams],
    )
