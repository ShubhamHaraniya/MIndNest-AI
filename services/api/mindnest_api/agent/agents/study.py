"""The Study agent: answers questions about the student's course content from their own materials,
with numbered citations.

It always searches first (the search is shown to the student as a step), puts the passages in its
instructions exactly as chat always has, and may search again with a different query if the first
passages do not cover the question."""

import time
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from mindnest_api.agent.agents.common import search_materials_tool
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.prompts import (
    CHAT_EXTRAS,
    NO_SOURCES,
    SYSTEM_TEMPLATE,
    attachments_section,
    language_rule,
    retrieval_query,
)

TOOL_NOTE = """

If the SOURCES above do not answer the question, you may call the search_materials tool once or \\
twice with a different, more specific query. Its passages continue the same numbering, and you \\
cite them the same way. Do not call it when the SOURCES already answer the question."""


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    previous_user = next((m.content for m in reversed(ctx.history) if m.role == "user"), None)
    query = step.query.strip() or retrieval_query(ctx.question, previous_user)

    # The first search is done for the agent, and shown to the student like any other tool call.
    number = ctx.next_step()
    ctx.emit({"type": "step", "id": number, "agent": "study", "tool": "search_materials",
              "summary": query[:200], "status": "running"})
    started = time.perf_counter()
    status = "done"
    try:
        found = await ctx.search(query)
    except Exception:
        status = "failed"
        raise
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        ctx.emit({"type": "step", "id": number, "agent": "study", "tool": "search_materials",
                  "summary": query[:200], "status": status, "ms": ms})
        await ctx.record(node="prepare", agent="study", tool="search_materials",
                         args={"query": query}, outcome=status, ms=ms)

    sources = f"SOURCES:\n{found.text}" if found.text else NO_SOURCES
    system = SYSTEM_TEMPLATE.format(
        language_rule=language_rule(ctx.user.answer_language), canary=ctx.canary, sources=sources,
    ) + TOOL_NOTE + CHAT_EXTRAS + attachments_section(ctx.attachment_text) + earlier_work(results)
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "study", "study agent",
        "answers questions about course content using the student's own uploaded materials, "
        "with citations. This is the default for any study question.",
        prepare,
        lambda ctx: [search_materials_tool(ctx, "study")],
    )
)
