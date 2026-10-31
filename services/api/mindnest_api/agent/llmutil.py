"""Small helpers around LangChain chat models: streaming one model turn, reading text from
chunks, and turning provider failures into the stable error codes the app already uses."""

import json
import logging
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from mindnest_agents.errors import AgentError, error_code
from mindnest_core.redact import redact

from mindnest_api.agent.context import AgentContext

logger = logging.getLogger("mindnest.agent")


def content_text(content: Any) -> str:
    """The plain text of a message's content. Providers return a string or a list of blocks;
    only text blocks count (reasoning and tool-use blocks are skipped)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def message_text(message: BaseMessage) -> str:
    return content_text(message.content)


def fail(exc: BaseException) -> AgentError:
    """The AgentError for a failed provider call. The provider's own text is never passed on."""
    code = error_code(exc)
    logger.warning("model call failed (%s): %s", code, redact(f"{type(exc).__name__}: {exc}")[:300])
    return AgentError(code)


async def run_model(
    ctx: AgentContext,
    llm: Any,
    messages: list[BaseMessage],
    config: RunnableConfig,
    *,
    stream: bool = True,
) -> AIMessage:
    """One model turn. Text is streamed to the student as it arrives, tagged with a turn number.
    If the turn ends with tool calls, the text of that turn is retracted ("discard"), because
    the answer is the text of the turn that does not call a tool."""
    turn = ctx.next_turn()
    full: Any = None
    try:
        async for chunk in llm.astream(messages, config=config):
            full = chunk if full is None else full + chunk
            piece = content_text(chunk.content)
            if piece and stream:
                ctx.emit({"type": "token", "text": piece, "turn": turn})
    except AgentError:
        raise
    except Exception as exc:
        raise fail(exc) from exc
    if full is None:
        raise AgentError("empty_response")
    ctx.add_usage(full)
    tool_calls = list(getattr(full, "tool_calls", None) or [])
    if tool_calls and stream:
        ctx.emit({"type": "discard", "turn": turn})
    if not tool_calls and not content_text(full.content).strip():
        raise AgentError("empty_response")
    return AIMessage(content=full.content, tool_calls=tool_calls, id=getattr(full, "id", None),
                     usage_metadata=getattr(full, "usage_metadata", None))


async def ask(
    ctx: AgentContext, llm: BaseChatModel, messages: list[BaseMessage], config: RunnableConfig
) -> str:
    """One model call whose reply is for the program, not the student (nothing is streamed)."""
    reply = await run_model(ctx, llm, messages, config, stream=False)
    return content_text(reply.content)


_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(reply: str) -> dict[str, Any] | None:
    match = _OBJECT.search(reply.strip())
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
