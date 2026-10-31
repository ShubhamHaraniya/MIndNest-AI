"""Direct chat: replies straight from the model. No search of the student's materials, no tools.
Used for greetings, thanks, small talk, questions about what MindNest can do, and anything that
needs nothing from the student's own data."""

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import (
    AGENTS,
    AgentSpec,
    Prepared,
    base_prompt,
    chat_messages,
    earlier_work,
    register,
)
from mindnest_api.agent.router import PlanStep

ROLE = """You chat with the student directly. You do not have the student's notes in front of you \\
for this reply, and you cannot search them from here.

- Greetings and thanks: answer warmly in one or two short sentences. Do not list features unless \\
asked.
- If the student asks what you can do, explain it simply using this list of helpers:
{helpers}
- If the student asks something about their own notes, subjects, quizzes, plans or assignments, \\
say you can look into that when they ask for it directly, and invite them to ask.
- For general knowledge or writing help that does not depend on their materials, just help. If \\
you are unsure of a fact, say so instead of guessing."""


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    helpers = "\n".join(f"  - {a.title}: {a.job}" for a in AGENTS.values() if a.name != "direct")
    system = base_prompt(ctx, "chat assistant", ROLE.format(helpers=helpers), earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "direct", "chat assistant",
        "answers greetings, thanks, small talk, questions about what you can do, and general "
        "questions that need nothing from the student's own materials. No search, no tools.",
        prepare,
    )
)
