"""How agent tools are built. Every tool is a LangChain StructuredTool that runs as the signed-in
student: it uses the run's database handle, so row-level security decides what it can see or
change. The wrapper adds what every tool needs: step events for the screen, a redacted record in
agent_steps, and errors turned into text the model can react to instead of crashing the run."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.errors import GraphBubbleUp
from mindnest_agents.errors import AgentError
from mindnest_core.redact import redact
from pydantic import BaseModel

from mindnest_api.agent.context import AgentContext
from mindnest_api.errors import AppError

logger = logging.getLogger("mindnest.agent")

MAX_TOOL_OUTPUT = 12000


class ToolFailure(Exception):
    """A tool could not do what was asked for a reason the model should hear about
    (unknown subject, nothing found). The message is shown to the model, not to the student."""


ToolFunc = Callable[..., Awaitable[str]]


async def via_route(call: Awaitable[Any]) -> Any:
    """Await an existing route function (the same code the screens use, so the same checks apply)
    and turn its error into text for the model."""
    try:
        return await call
    except AppError as exc:
        raise ToolFailure(exc.message) from exc


def agent_tool(
    ctx: AgentContext,
    agent: str,
    name: str,
    description: str,
    schema: type[BaseModel],
    func: ToolFunc,
    summary: Callable[[dict[str, Any]], str] | None = None,
    untrusted: bool = True,
    approval: bool = False,
) -> StructuredTool:
    """`untrusted=True` (the default) treats the tool's output as data written by the student or
    taken from their documents: it is made safe before the model reads it. Tools that already
    prepare their own text (the ones that return numbered sources) pass False.

    `approval=True` marks a tool that changes something outside MindNest (a calendar) and must pause
    for the student's decision. Such a tool calls langgraph's `interrupt()` before it does anything,
    and the graph runs it alone, never in the same round as other tools (see graph.tools_node)."""
    async def run(**kwargs: Any) -> str:
        step = ctx.next_step()
        label = (summary(kwargs) if summary else "")[:200]
        ctx.emit({"type": "step", "id": step, "agent": agent, "tool": name, "summary": label, "status": "running"})
        started = time.perf_counter()
        status = "done"
        try:
            out = await func(ctx, **kwargs)
        except GraphBubbleUp:  # a pause for the student's approval is not a failure
            raise
        except AgentError:
            raise
        except ToolFailure as exc:
            status, out = "failed", f"ERROR: {exc}"
        except Exception as exc:
            logger.warning("tool %s failed: %s", name, redact(f"{type(exc).__name__}: {exc}")[:300])
            status, out = "failed", "ERROR: this tool failed. Tell the student you could not do it."
        ms = int((time.perf_counter() - started) * 1000)
        ctx.emit({"type": "step", "id": step, "agent": agent, "tool": name, "summary": label,
                  "status": status, "ms": ms})
        await ctx.record(node="tools", agent=agent, tool=name, args=kwargs,
                         outcome=status if status == "done" else f"failed: {out[:120]}", ms=ms)
        out = out[:MAX_TOOL_OUTPUT]
        # With the guardrails on, the tool-result rail (graph.tools_node) makes the text safe and
        # reports what it found; without them the tool does it here.
        if ctx.guard is None and untrusted and status == "done":
            return ctx.untrusted(out)
        return out

    return StructuredTool.from_function(
        coroutine=run, name=name, description=description, args_schema=schema,
        handle_validation_error=True, metadata={"approval": approval},
    )
