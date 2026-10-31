"""The Materials agent: finds, opens and summarises the student's own uploaded files from chat."""

from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.agent.agents.common import list_subjects_tool
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, base_prompt, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.agent.tools import ToolFailure, agent_tool
from mindnest_api.prompts import format_numbered_sources
from mindnest_api.retrieval import Passage, retrieve

ROLE = """You help the student work with their own uploaded files (notes, slides, PDFs).

- To see what they have, call list_materials. To read a file, call read_material (the start, a \\
page, or the parts about a question). For "what is this file about" or a summary, call \\
get_material_overview, then write the summary yourself from the passages.
- Passages come back as numbered <source> blocks. Cite what you take from them like [1] or [2][3], \\
and cite only numbers that exist.
- A file that is still processing or failed cannot be read: say so plainly.
- Do not paste whole files. Quote at most a short line; explain in your own words.
- Never invent a file name. Use the names and ids from tool results."""

CHUNKS_PER_READ = 6
OVERVIEW_CHUNKS = 10


class ListArgs(BaseModel):
    subject: str | None = Field(default=None, description="Only files in this subject. Leave out for all subjects.")


async def _list_materials(ctx: AgentContext, subject: str | None = None) -> str:
    sid: UUID | None = None
    if subject:
        found = ctx.find_subject(subject)
        if found is None:
            raise ToolFailure(f"No subject matches '{subject}'. Their subjects are: {ctx.subject_names()}.")
        sid = found.id
    elif ctx.subject_id:
        sid = ctx.subject_id
    async with ctx.db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT m.id, m.filename, m.kind, m.status, s.name AS subject, "
                        "(SELECT count(*) FROM chunks c WHERE c.material_id = m.id) AS parts "
                        "FROM materials m JOIN subjects s ON s.id = m.subject_id "
                        "WHERE m.deleted_at IS NULL AND (CAST(:s AS uuid) IS NULL OR m.subject_id = CAST(:s AS uuid)) "
                        "ORDER BY m.created_at DESC LIMIT 40"
                    ),
                    {"s": str(sid) if sid else None},
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        return "The student has no files here yet."
    ctx.emit({"type": "card", "kind": "materials", "data": {"items": [
        {"id": str(r["id"]), "filename": r["filename"], "subject": r["subject"], "status": r["status"],
         "kind": r["kind"]} for r in rows[:12]], "total": len(rows)}})
    return "\n".join(
        f"- id {r['id']} | {r['filename']} | {r['subject']} | {r['kind']} | {r['status']} | {r['parts']} parts"
        for r in rows
    )


async def _resolve(ctx: AgentContext, reference: str) -> dict[str, Any]:
    ref = reference.strip()
    async with ctx.db.session() as session:
        try:
            rows = (
                (
                    await session.execute(
                        text("SELECT m.id, m.filename, m.status, m.subject_id, s.name AS subject FROM materials m "
                             "JOIN subjects s ON s.id = m.subject_id WHERE m.deleted_at IS NULL AND m.id = :i"),
                        {"i": UUID(ref)},
                    )
                )
                .mappings()
                .all()
            )
        except ValueError:
            escaped = ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = (
                (
                    await session.execute(
                        text("SELECT m.id, m.filename, m.status, m.subject_id, s.name AS subject FROM materials m "
                             "JOIN subjects s ON s.id = m.subject_id WHERE m.deleted_at IS NULL "
                             "AND m.filename ILIKE :p ORDER BY m.created_at DESC LIMIT 6"),
                        {"p": f"%{escaped}%"},
                    )
                )
                .mappings()
                .all()
            )
    if not rows:
        raise ToolFailure(f"No file matches '{reference}'. Use list_materials to see the student's files.")
    if len(rows) > 1:
        names = "; ".join(f"{r['filename']} (id {r['id']})" for r in rows)
        raise ToolFailure(f"More than one file matches '{reference}': {names}. Ask which one, or use its id.")
    row = dict(rows[0])
    if row["status"] != "ready":
        raise ToolFailure(f"'{row['filename']}' is not readable yet (its status is {row['status']}).")
    return row


def _passages(rows: list[Any], material: dict[str, Any]) -> list[Passage]:
    return [
        Passage(r["id"], material["id"], material["filename"], r["page"], r["section"], r["text"])
        for r in rows
    ]


def _show(ctx: AgentContext, passages: list[Passage], material: dict[str, Any]) -> str:
    numbered, _ = ctx.register(passages)
    ctx.emit({"type": "sources", "items": list(ctx.sources), "degraded": False})
    ctx.emit({"type": "card", "kind": "material", "data": {
        "id": str(material["id"]), "filename": material["filename"], "subject": material["subject"]}})
    return "SOURCES:\n" + format_numbered_sources(numbered)


class ReadArgs(BaseModel):
    material: str = Field(description="File name (or part of it) or id, from list_materials.")
    page: int | None = Field(default=None, ge=1, description="Read this page.")
    query: str | None = Field(default=None, description="Read the parts of the file that are about this.", max_length=300)


async def _read_material(ctx: AgentContext, material: str, page: int | None = None, query: str | None = None) -> str:
    doc = await _resolve(ctx, material)
    async with ctx.db.session() as session:
        if query:
            found = await retrieve(
                session, ctx.models, query, subject_id=doc["subject_id"],
                candidates=ctx.settings.retrieval_candidates, top_k=30,
            )
            passages = [p for p in found.passages if p.material_id == doc["id"]][:CHUNKS_PER_READ]
        else:
            rows = (
                (
                    await session.execute(
                        text("SELECT c.id, c.page, c.section, c.text FROM chunks c "
                             "WHERE c.material_id = :m AND c.is_active "
                             "AND (CAST(:p AS integer) IS NULL OR c.page = CAST(:p AS integer)) "
                             "ORDER BY c.page NULLS LAST, c.ctid LIMIT :n"),
                        {"m": doc["id"], "p": page, "n": CHUNKS_PER_READ},
                    )
                )
                .mappings()
                .all()
            )
            passages = _passages(list(rows), doc)
    if not passages:
        return f"Nothing found in '{doc['filename']}' for that request."
    return _show(ctx, passages, doc)


class OverviewArgs(BaseModel):
    material: str = Field(description="File name (or part of it) or id.")


async def _overview(ctx: AgentContext, material: str) -> str:
    doc = await _resolve(ctx, material)
    async with ctx.db.session() as session:
        rows = list(
            (
                await session.execute(
                    text("SELECT c.id, c.page, c.section, c.text FROM chunks c "
                         "WHERE c.material_id = :m AND c.is_active ORDER BY c.page NULLS LAST, c.ctid"),
                    {"m": doc["id"]},
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        return f"'{doc['filename']}' has no readable text."
    # Evenly spaced parts, so the summary covers the whole file and not only its beginning.
    step = max(1, len(rows) // OVERVIEW_CHUNKS)
    picked = rows[::step][:OVERVIEW_CHUNKS]
    return f"The file has {len(rows)} parts; here are {len(picked)} spread across it.\n" + _show(ctx, _passages(picked, doc), doc)


def materials_tools(ctx: AgentContext) -> list[Any]:
    return [
        agent_tool(ctx, "materials", "list_materials",
                   "List the student's uploaded files (name, subject, status).",
                   ListArgs, _list_materials, lambda a: a.get("subject") or ""),
        agent_tool(ctx, "materials", "read_material",
                   "Read part of one file: its start, a page, or the parts about a question.",
                   ReadArgs, _read_material, lambda a: a.get("material", ""), untrusted=False),
        agent_tool(ctx, "materials", "get_material_overview",
                   "Get passages spread across one whole file, to write a summary from.",
                   OverviewArgs, _overview, lambda a: a.get("material", ""), untrusted=False),
        list_subjects_tool(ctx, "materials"),
    ]


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    system = base_prompt(ctx, "materials agent", ROLE, f"\nThe student's subjects: {ctx.subject_names()}." + earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "materials", "materials agent",
        "lists, opens, reads and summarises the student's uploaded files (\"what files do I have\", "
        "\"summarise my OS notes\", \"show page 3 of lecture1.pdf\").",
        prepare, materials_tools,
    )
)
