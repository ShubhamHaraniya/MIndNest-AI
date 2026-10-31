"""Saving a graph's state between steps, so a run can stop for approval and continue later.

LangGraph's Postgres checkpointer writes to three tables (created by migration 0013, with
row-level security). Each run opens its own database connection as the application role and sets
`app.user_id` on it, so Postgres itself refuses to read or write another student's checkpoints,
whatever the code above it does. The connection is never shared or pooled, which is what makes a
session-level setting safe here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row


def psycopg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+asyncpg://… -> postgresql://… (what psycopg expects)."""
    scheme, sep, rest = sqlalchemy_url.partition("://")
    return f"{scheme.split('+')[0]}{sep}{rest}"


def thread_id(user_id: UUID, conversation_id: UUID) -> str:
    """The checkpoint thread of one conversation. The row-level-security policy reads the part
    before the colon, so every thread id MUST be built here."""
    return f"{user_id}:{conversation_id}"


@asynccontextmanager
async def open_checkpointer(database_url: str, user_id: UUID) -> AsyncIterator[AsyncPostgresSaver]:
    conn = await psycopg.AsyncConnection.connect(
        psycopg_dsn(database_url), autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    try:
        # Session-level (not transaction-local): the saver issues many separate statements.
        await conn.execute("SELECT set_config('app.user_id', %s, false)", (str(user_id),))
        yield AsyncPostgresSaver(conn)
    finally:
        await conn.close()
