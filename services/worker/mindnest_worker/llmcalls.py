"""Calls to the student's own AI provider that background jobs share (quizzes, assignments)."""

import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing

from mindnest_api.llm import LLM, PROVIDERS, ChatMessage, LLMError
from mindnest_api.vault import decrypt
from mindnest_core.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

type Sleep = Callable[[float], Awaitable[None]]

RATE_LIMIT_BACKOFF = (10.0, 30.0, 60.0)

logger = logging.getLogger("mindnest.jobs")


class JobFailed(Exception):
    """A background job could not finish. `code` is short and safe to show in the student's language."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def collect(
    llm: LLM, provider: str, api_key: str, model: str, system: str, user: str,
    sleep: Sleep, backoff: tuple[float, ...],
) -> str:
    """One provider call, collected into text. A rate-limited call is retried after a pause."""
    attempt = 0
    while True:
        try:
            pieces: list[str] = []
            async with aclosing(
                llm.stream(provider, api_key, model, system, [ChatMessage("user", user)])
            ) as stream:
                async for piece in stream:
                    pieces.append(piece)
            reply = "".join(pieces)
            if not reply.strip():
                raise LLMError("empty_response")
            return reply
        except LLMError as exc:
            if exc.code == "rate_limited" and attempt < len(backoff):
                await sleep(backoff[attempt])
                attempt += 1
                continue
            raise


async def key_for(session: AsyncSession, settings: Settings, provider: str | None) -> tuple[str, str, str]:
    """(provider, model, decrypted key) of the student's saved key."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT provider, model, ciphertext FROM provider_keys "
                    "WHERE (CAST(:p AS text) IS NULL OR provider = :p) "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"p": provider},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise JobFailed("no_provider_key")
    name = str(row["provider"])
    if name not in PROVIDERS:
        raise JobFailed("unknown_provider")
    try:
        key = decrypt(settings.secret_key, row["ciphertext"])
    except Exception as exc:
        raise JobFailed("key_unreadable") from exc
    return name, str(row["model"] or PROVIDERS[name].default_model), key
