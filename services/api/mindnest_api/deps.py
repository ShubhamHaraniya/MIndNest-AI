"""Request dependencies: who is signed in, and a database handle scoped to them."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request, Response
from mindnest_agents.guardrails import Guardrails, get_guardrails
from mindnest_core.db import user_session
from mindnest_core.googleoauth import GoogleClient
from mindnest_core.settings import get_settings
from mindnest_core.storage import ObjectStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mindnest_api.calendar_gateway import CalendarGateway
from mindnest_api.errors import AppError
from mindnest_api.jobs import IngestQueue
from mindnest_api.llm import LLM
from mindnest_api.mailer import Mailer
from mindnest_api.ratelimit import Limiter
from mindnest_api.retrieval import ModelClient
from mindnest_api.schemas import USER_COLUMNS, UserOut
from mindnest_api.security import hash_token


# Builds the chat model for one provider: (provider, model, api_key, **options) -> model.
ChatModelFactory = Callable[..., Any]


class CurrentUser(UserOut):
    session_id: UUID


def _unauthorized() -> AppError:
    return AppError(401, "not_authenticated", "Please sign in to continue.")


async def get_current_user(request: Request) -> CurrentUser:
    """Resolve the session cookie to an active user, or raise 401."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _unauthorized()
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session, session.begin():
        row = (
            (
                await session.execute(
                    text(
                        f"""
                        SELECT {USER_COLUMNS}, se.id AS session_id
                        FROM sessions se
                        JOIN users u ON u.id = se.user_id
                        WHERE se.token_hash = :hash
                          AND se.expires_at > now()
                          AND u.status = 'active'
                        """
                    ),
                    {"hash": hash_token(token)},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise _unauthorized()
        # Touch at most once a minute so reads do not turn into a write per request.
        await session.execute(
            text(
                "UPDATE sessions SET last_seen_at = now() "
                "WHERE id = :id AND last_seen_at < now() - interval '1 minute'"
            ),
            {"id": row["session_id"]},
        )
    return CurrentUser(**row)


AuthUser = Annotated[CurrentUser, Depends(get_current_user)]


class UserDb:
    """Opens transactions whose row-level security context is the signed-in user.

    Use as `async with db.session() as s:`. The transaction commits when the block exits
    normally, so the data is durable before the handler returns its response.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession], user_id: UUID) -> None:
        self._factory = factory
        self._user_id = user_id

    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        return user_session(self._factory, self._user_id)


def get_user_db(request: Request, user: AuthUser) -> UserDb:
    return UserDb(request.app.state.session_factory, user.id)


UserDbDep = Annotated[UserDb, Depends(get_user_db)]


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer  # type: ignore[no-any-return]


def get_limiter(request: Request) -> Limiter:
    return request.app.state.limiter  # type: ignore[no-any-return]


def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage  # type: ignore[no-any-return]


def get_queue(request: Request) -> IngestQueue:
    return request.app.state.queue  # type: ignore[no-any-return]


def get_llm(request: Request) -> LLM:
    return request.app.state.llm  # type: ignore[no-any-return]


def get_models(request: Request) -> ModelClient:
    return request.app.state.models  # type: ignore[no-any-return]


def get_chat_models(request: Request) -> ChatModelFactory:
    return request.app.state.chat_models  # type: ignore[no-any-return]


def get_google(request: Request) -> GoogleClient:
    return request.app.state.google  # type: ignore[no-any-return]


def get_guardrails_dep(request: Request) -> Guardrails | None:
    """The shared guardrails engine, or None when GUARDRAILS_ENABLED is off."""
    settings = get_settings()
    if not settings.guardrails_enabled:
        return None
    found = getattr(request.app.state, "guardrails", None)
    return found if found is not None else get_guardrails(settings.guardrails_judge_timeout_seconds)


def get_calendar_gateway(request: Request) -> CalendarGateway:
    return request.app.state.calendar_gateway  # type: ignore[no-any-return]


ChatModelsDep = Annotated[ChatModelFactory, Depends(get_chat_models)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
LLMDep = Annotated[LLM, Depends(get_llm)]
ModelsDep = Annotated[ModelClient, Depends(get_models)]
QueueDep = Annotated[IngestQueue, Depends(get_queue)]
GoogleDep = Annotated[GoogleClient, Depends(get_google)]
CalendarGatewayDep = Annotated[CalendarGateway, Depends(get_calendar_gateway)]
GuardrailsDep = Annotated[Guardrails | None, Depends(get_guardrails_dep)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
LimiterDep = Annotated[Limiter, Depends(get_limiter)]


def client_ip(request: Request) -> str:
    """Best-effort client address for rate limiting.

    Behind the web app's proxy the first X-Forwarded-For entry is the browser. A client can
    forge that header, so this slows abuse; it is not a security boundary.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        path="/",
    )
