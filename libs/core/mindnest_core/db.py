"""Database helpers. Every user-facing query must run through user_session()."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def user_session(
    factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> AsyncIterator[AsyncSession]:
    """Open a transaction whose row-level security context is the given user.

    The setting is transaction-local (the third argument of set_config is true), so it
    cannot leak to the next request that reuses the pooled connection. The transaction
    commits when the block exits normally and rolls back on an exception.
    """
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
        )
        yield session


def as_json(value: Any) -> Any:
    """jsonb read through a raw text() query arrives as a JSON string; decode it to Python."""
    return json.loads(value) if isinstance(value, str) else value
