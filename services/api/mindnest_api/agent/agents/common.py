"""Tools shared by several agents."""

from typing import Any

from pydantic import BaseModel, Field

from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.tools import ToolFailure, agent_tool


class SearchArgs(BaseModel):
    query: str = Field(description="What to look for, written as a specific search phrase.", max_length=300)
    subject: str | None = Field(default=None, description="Optional subject name to search in. Leave out to use the chat's subject, or all subjects.")


async def _search(ctx: AgentContext, query: str, subject: str | None = None) -> str:
    scope: Any = "default"
    if subject:
        found = ctx.find_subject(subject)
        if found is None:
            raise ToolFailure(f"No single subject matches '{subject}'. The student's subjects are: {ctx.subject_names()}.")
        scope = found.id
    result = await ctx.search(query, scope)
    if not result.text:
        return "No passages in the student's materials match this search."
    note = "" if not result.degraded else "(Meaning search was unavailable, so this used word matching only.)\n"
    return f"{note}SOURCES:\n{result.text}"


class NoArgs(BaseModel):
    pass


async def _list_subjects(ctx: AgentContext) -> str:
    if not ctx.subjects:
        return "The student has no subjects yet."
    return "\n".join(f"- {s.name}: {s.ready_materials} processed file(s)" for s in ctx.subjects)


def list_subjects_tool(ctx: AgentContext, agent: str) -> Any:
    return agent_tool(
        ctx, agent, "list_subjects",
        "List the student's subjects and how many processed files each has.",
        NoArgs, _list_subjects, lambda a: "", untrusted=True,
    )


def today_line(ctx: AgentContext) -> str:
    """Today's date where the student lives, so "next Friday" can be turned into a date."""
    from datetime import UTC, datetime

    from mindnest_core.plannerlogic import local_today

    today = local_today(ctx.user.timezone, datetime.now(UTC))
    return f"Today is {today.isoformat()} ({today.strftime('%A')}) where the student lives."


def search_materials_tool(ctx: AgentContext, agent: str) -> Any:
    return agent_tool(
        ctx, agent, "search_materials",
        "Search the student's own uploaded materials (notes, slides, PDFs) for passages about a "
        "topic. Returns numbered <source> passages. Cite them with their number in square "
        "brackets, like [3].",
        SearchArgs, _search, lambda a: a.get("query", ""), untrusted=False,
    )
