"""Bookkeeping for agent runs: one agent_runs row per student message, one agent_steps row per
thing an agent did (a routing decision, a tool call). Steps keep REDACTED arguments only: personal
data is masked and long text is cut, so the table is safe to show in the Agents evaluation view.

All functions take a session from mindnest_core.db.user_session, so row-level security applies.
"""

import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import AgentError
from .tracing import mask_payload, mask_text

STATUSES = ("running", "interrupted", "completed", "failed", "cancelled")
ARG_STRING_LIMIT = 300
ERROR_LIMIT = 300


def redact_args(args: Any, known: Iterable[str] = ()) -> Any:
    return mask_payload(args, known, limit=ARG_STRING_LIMIT)


async def start_run(
    session: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID | None,
    graph_version: str,
    thread_id: str | None = None,
    run_id: UUID | None = None,
) -> UUID:
    new_id = run_id or uuid4()
    await session.execute(
        text(
            "INSERT INTO agent_runs (id, user_id, conversation_id, graph_version, thread_id, "
            "langsmith_run_id) VALUES (:id, :user, :conv, :ver, :thread, :ls)"
        ),
        {
            "id": new_id, "user": user_id, "conv": conversation_id, "ver": graph_version,
            "thread": thread_id,
            # The agent run id is also the root run id in LangSmith (see tracing.make_tracing).
            "ls": str(new_id),
        },
    )
    return new_id


async def record_step(
    session: AsyncSession,
    run_id: UUID,
    *,
    node: str,
    agent: str | None = None,
    tool: str | None = None,
    args: Any = None,
    outcome: str | None = None,
    duration_ms: int | None = None,
    known_secrets: Iterable[str] = (),
) -> int:
    """Append a step. Returns its sequence number (1, 2, 3 …)."""
    # Two steps of one run must not pick the same number, so serialise them per run.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:rid, 0))"), {"rid": str(run_id)})
    safe_args = None if args is None else json.dumps(redact_args(args, known_secrets))
    row = await session.execute(
        text(
            "INSERT INTO agent_steps (run_id, seq, node, agent, tool, args_redacted, outcome, duration_ms) "
            "SELECT :rid, COALESCE(MAX(seq), 0) + 1, :node, :agent, :tool, CAST(:args AS jsonb), "
            ":outcome, :dur FROM agent_steps WHERE run_id = :rid RETURNING seq"
        ),
        {
            "rid": run_id, "node": node, "agent": agent, "tool": tool, "args": safe_args,
            "outcome": None if outcome is None else mask_text(outcome, known_secrets, ARG_STRING_LIMIT),
            "dur": duration_ms,
        },
    )
    return row.scalar_one()  # type: ignore[no-any-return]


async def set_route(session: AsyncSession, run_id: UUID, route: dict[str, Any]) -> None:
    """Remember what the orchestrator decided (which agent(s) and why)."""
    await session.execute(
        text("UPDATE agent_runs SET route = CAST(:route AS jsonb), updated_at = now() WHERE id = :id"),
        {"route": json.dumps(redact_args(route)), "id": run_id},
    )


async def finish_run(
    session: AsyncSession,
    run_id: UUID,
    *,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    interrupt: Any = None,
) -> None:
    """Close a run, or park it as 'interrupted' while it waits for the student's approval."""
    if status not in STATUSES or status == "running":
        raise AgentError("bad_request")
    await session.execute(
        text(
            "UPDATE agent_runs SET status = :status, prompt_tokens = COALESCE(:pt, prompt_tokens), "
            "completion_tokens = COALESCE(:ct, completion_tokens), latency_ms = COALESCE(:lat, latency_ms), "
            "error = :err, interrupt = CAST(:intr AS jsonb), updated_at = now() WHERE id = :id"
        ),
        {
            "status": status, "pt": prompt_tokens, "ct": completion_tokens, "lat": latency_ms,
            "err": None if error is None else mask_text(error, (), ERROR_LIMIT),
            "intr": None if interrupt is None else json.dumps(redact_args(interrupt)),
            "id": run_id,
        },
    )


async def resume_run(session: AsyncSession, run_id: UUID) -> bool:
    """Move an interrupted run back to running. False if it was not waiting for approval."""
    row = await session.execute(
        text(
            "UPDATE agent_runs SET status = 'running', interrupt = NULL, updated_at = now() "
            "WHERE id = :id AND status = 'interrupted' RETURNING id"
        ),
        {"id": run_id},
    )
    return row.first() is not None
