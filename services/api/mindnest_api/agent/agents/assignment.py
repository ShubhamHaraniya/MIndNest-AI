"""The Assignment agent: keeps track of assignments and gets coaching help on them.

The help (a breakdown, an outline, feedback on a draft) is written in the background by the same
worker as on the Assignments page and is built to coach, not to write the assignment for the
student. This agent starts that job and shows a card that fills in when the result is ready."""

from datetime import UTC, date, datetime, time
from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from mindnest_core.plannerlogic import local_zone
from pydantic import BaseModel, Field

from mindnest_api.agent.agents.common import NoArgs, list_subjects_tool, today_line
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, base_prompt, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.agent.tools import ToolFailure, agent_tool, via_route
from mindnest_api.routes import assignments as assignment_routes

ROLE = """You help the student keep track of their assignments and get coaching on them.

- {today}
- To see their assignments call list_assignments. To read one, call get_assignment.
- To save a new assignment call add_assignment (title, brief, subject, due date). To change one, or to \\
save a draft the student pasted, call update_assignment.
- For help call get_help with a kind: "breakdown" (split the task into steps), "outline" (a structure \\
for the answer) or "feedback" (comments on the student's draft; needs a saved draft). It runs in the \\
background and a card shows the result when it is ready; say so in one sentence and do not wait.
- You coach. You never write the assignment, the essay or the solution for the student, even if \\
asked. Offer a breakdown, an outline, or feedback on their own draft instead.
- Never say something was saved or started unless a tool result confirms it. Never invent ids."""


def _id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ToolFailure("That is not a valid assignment id. Use an id from list_assignments.") from exc


def _due(ctx: AgentContext, day: date | None) -> datetime | None:
    """A due day means the end of that day where the student lives."""
    if day is None:
        return None
    return datetime.combine(day, time(23, 59), tzinfo=local_zone(ctx.user.timezone)).astimezone(UTC)


def _subject_id(ctx: AgentContext, subject: str | None) -> UUID | None:
    if not subject:
        return None
    found = ctx.find_subject(subject)
    if found is None:
        raise ToolFailure(f"No subject matches '{subject}'. Their subjects are: {ctx.subject_names()}.")
    return found.id


async def _list_assignments(ctx: AgentContext) -> str:
    rows = await via_route(assignment_routes.list_assignments(ctx.user, ctx.db))
    if not rows:
        return "The student has no assignments saved."
    return "\n".join(
        f"- id {a.id} | {a.title} | {a.status} | due {a.due_at.date().isoformat() if a.due_at else 'no date'}"
        f" | brief: {'yes' if a.has_brief else 'no'} | draft: {'yes' if a.has_draft else 'no'}"
        + (f" | {a.subject_name}" if a.subject_name else "")
        for a in rows[:40]
    )


class AssignmentIdArgs(BaseModel):
    assignment_id: str = Field(description="An assignment id from list_assignments.")


async def _get_assignment(ctx: AgentContext, assignment_id: str) -> str:
    a = await via_route(assignment_routes.get_assignment(_id(assignment_id), ctx.user, ctx.db))
    ctx.emit({"type": "card", "kind": "assignment", "data": {
        "id": str(a.id), "title": a.title, "status": a.status, "subject": a.subject_name,
        "due_at": a.due_at.isoformat() if a.due_at else None}})
    brief = a.brief[:3000] or "(no brief saved)"
    draft = a.draft[:3000] or "(no draft saved)"
    return f"Assignment '{a.title}' ({a.status}).\nBRIEF:\n{brief}\nDRAFT:\n{draft}"


class AddArgs(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    brief: str = Field(default="", max_length=8000, description="The task description, if the student gave it.")
    subject: str | None = None
    due: date | None = Field(default=None, description="Due day, YYYY-MM-DD.")


async def _add_assignment(
    ctx: AgentContext, title: str, brief: str = "", subject: str | None = None, due: date | None = None
) -> str:
    body = assignment_routes.AssignmentIn(
        title=title, brief=brief, subject_id=_subject_id(ctx, subject), due_at=_due(ctx, due))
    a = await via_route(assignment_routes.create_assignment(body, ctx.user, ctx.db, ctx.limiter))
    ctx.emit({"type": "card", "kind": "assignment", "data": {
        "id": str(a.id), "title": a.title, "status": a.status, "subject": a.subject_name,
        "due_at": a.due_at.isoformat() if a.due_at else None}})
    return f"Assignment saved: id {a.id}, '{a.title}'."


class UpdateArgs(BaseModel):
    assignment_id: str
    title: str | None = Field(default=None, min_length=1, max_length=120)
    brief: str | None = Field(default=None, max_length=8000)
    draft: str | None = Field(default=None, max_length=20000, description="The student's own draft, exactly as pasted.")
    due: date | None = Field(default=None, description="New due day, YYYY-MM-DD.")
    status: Literal["todo", "in_progress", "done"] | None = None


async def _update_assignment(
    ctx: AgentContext, assignment_id: str, title: str | None = None, brief: str | None = None,
    draft: str | None = None, due: date | None = None, status: str | None = None,
) -> str:
    changes: dict[str, Any] = {}
    for name, value in (("title", title), ("brief", brief), ("draft", draft), ("status", status)):
        if value is not None:
            changes[name] = value
    if due is not None:
        changes["due_at"] = _due(ctx, due)
    if not changes:
        raise ToolFailure("Nothing to change.")
    body = assignment_routes.AssignmentPatch(**changes)
    a = await via_route(assignment_routes.update_assignment(_id(assignment_id), body, ctx.user, ctx.db))
    return f"Assignment updated: '{a.title}' is {a.status}; changed: {', '.join(changes)}."


class HelpArgs(BaseModel):
    assignment_id: str
    kind: Literal["breakdown", "outline", "feedback"]


async def _get_help(ctx: AgentContext, assignment_id: str, kind: str) -> str:
    aid = _id(assignment_id)
    body = assignment_routes.RunIn(kind=kind, language=ctx.user.answer_language or ctx.user.ui_language,  # type: ignore[arg-type]
                                   provider=ctx.provider, model=ctx.model or None)  # type: ignore[arg-type]
    run = await via_route(assignment_routes.start_run(aid, body, ctx.user, ctx.db, ctx.queue, ctx.limiter))
    a = await via_route(assignment_routes.get_assignment(aid, ctx.user, ctx.db))
    ctx.emit({"type": "card", "kind": "assignment_run", "data": {
        "assignment_id": str(aid), "run_id": str(run.id), "kind": kind, "title": a.title}})
    return f"A {kind} for '{a.title}' is being written (run {run.id}). A card shows it when ready."


def assignment_tools(ctx: AgentContext) -> list[Any]:
    return [
        agent_tool(ctx, "assignment", "list_assignments", "List the student's assignments.", NoArgs, _list_assignments, lambda a: ""),
        agent_tool(ctx, "assignment", "get_assignment", "Read one assignment with its brief and draft.", AssignmentIdArgs,
                   _get_assignment, lambda a: a.get("assignment_id", "")),
        agent_tool(ctx, "assignment", "add_assignment", "Save a new assignment.", AddArgs, _add_assignment,
                   lambda a: a.get("title", "")),
        agent_tool(ctx, "assignment", "update_assignment", "Change an assignment, or save the student's draft.", UpdateArgs,
                   _update_assignment, lambda a: ", ".join(k for k in ("title", "brief", "draft", "due", "status") if a.get(k) is not None)),
        agent_tool(ctx, "assignment", "get_help", "Start a coaching breakdown, outline, or feedback on the draft (written in the background).",
                   HelpArgs, _get_help, lambda a: a.get("kind", "")),
        list_subjects_tool(ctx, "assignment"),
    ]


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    system = base_prompt(ctx, "assignment agent", ROLE.format(today=today_line(ctx)),
                         f"\nThe student's subjects: {ctx.subject_names()}." + earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "assignment", "assignment agent",
        "saves and updates assignments and drafts, and starts coaching help on them (a breakdown, "
        "an outline, or feedback on the student's own draft). It never writes the assignment.",
        prepare, assignment_tools,
    )
)
