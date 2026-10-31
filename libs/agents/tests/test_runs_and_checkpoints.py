"""Run records and the checkpoint tables, against a real migrated Postgres (skips if unreachable)."""

import uuid
from typing import Any, TypedDict

import psycopg.errors
import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mindnest_agents import GRAPH_VERSION, runs
from mindnest_agents.checkpoint import open_checkpointer, psycopg_dsn, thread_id
from mindnest_agents.errors import AgentError
from mindnest_core.db import make_engine, make_session_factory, user_session
from mindnest_core.settings import get_settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest_asyncio.fixture
async def env():
    settings = get_settings()
    admin = make_engine(settings.migration_database_url)
    app = make_engine(settings.database_url)
    try:
        async with admin.connect() as conn:
            await conn.execute(text("SELECT 1 FROM checkpoints LIMIT 1"))
    except Exception as exc:
        await admin.dispose()
        await app.dispose()
        pytest.skip(f"database with migration 0013 not available: {exc}")
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    conversations = {user_a: uuid.uuid4(), user_b: uuid.uuid4()}
    async with admin.begin() as conn:
        for uid, cid in conversations.items():
            await conn.execute(
                text("INSERT INTO users (id, email, password_hash, display_name) VALUES (:i, :e, 'x', 'T')"),
                {"i": uid, "e": f"{uid}@test.local"},
            )
            await conn.execute(
                text("INSERT INTO conversations (id, user_id, title) VALUES (:c, :u, 'Chat')"),
                {"c": cid, "u": uid},
            )
    yield settings, admin, make_session_factory(app), user_a, user_b, conversations
    async with admin.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": user_a, "b": user_b})
    await admin.dispose()
    await app.dispose()


# --------------------------------------------------------------------------------- run records


async def test_run_lifecycle_and_redacted_steps(env) -> None:
    _, admin, factory, user_a, _, convs = env
    async with user_session(factory, user_a) as s:
        run_id = await runs.start_run(
            s, user_id=user_a, conversation_id=convs[user_a], graph_version=GRAPH_VERSION,
            thread_id=thread_id(user_a, convs[user_a]),
        )
        await runs.set_route(s, run_id, {"agent": "calendar", "reason": "asked to book, call 9876543210"})
        n1 = await runs.record_step(s, run_id, node="router", agent="router", outcome="calendar")
        n2 = await runs.record_step(
            s, run_id, node="tools", agent="calendar", tool="create_event",
            args={"title": "Viva", "attendee": "priya.s@gmail.com", "notes": "x" * 2000}, duration_ms=42,
        )
        await runs.finish_run(s, run_id, status="completed", prompt_tokens=10, completion_tokens=5, latency_ms=900)
    assert (n1, n2) == (1, 2)
    async with admin.connect() as conn:
        run = (await conn.execute(text("SELECT * FROM agent_runs WHERE id = :i"), {"i": run_id})).mappings().one()
        steps = (await conn.execute(text("SELECT * FROM agent_steps WHERE run_id = :i ORDER BY seq"), {"i": run_id})).mappings().all()
    assert run["status"] == "completed" and run["langsmith_run_id"] == str(run_id)
    assert run["route"]["agent"] == "calendar" and "9876543210" not in str(run["route"])
    assert steps[1]["tool"] == "create_event" and steps[1]["duration_ms"] == 42
    assert "priya.s@gmail.com" not in str(steps[1]["args_redacted"])
    assert len(str(steps[1]["args_redacted"]["notes"])) < 400


async def test_a_run_can_wait_for_approval_and_continue(env) -> None:
    _, _, factory, user_a, _, convs = env
    async with user_session(factory, user_a) as s:
        run_id = await runs.start_run(s, user_id=user_a, conversation_id=convs[user_a], graph_version=GRAPH_VERSION)
        await runs.finish_run(s, run_id, status="interrupted", interrupt={"kind": "approve_event", "title": "Viva"})
    async with user_session(factory, user_a) as s:
        assert await runs.resume_run(s, run_id) is True
        assert await runs.resume_run(s, run_id) is False  # not waiting any more
        status = (await s.execute(text("SELECT status, interrupt FROM agent_runs WHERE id = :i"), {"i": run_id})).one()
    assert status[0] == "running" and status[1] is None


async def test_bad_finish_status_is_refused(env) -> None:
    _, _, factory, user_a, _, convs = env
    async with user_session(factory, user_a) as s:
        run_id = await runs.start_run(s, user_id=user_a, conversation_id=convs[user_a], graph_version=GRAPH_VERSION)
        for bad in ("running", "weird"):
            with pytest.raises(AgentError):
                await runs.finish_run(s, run_id, status=bad)


async def test_errors_are_masked_and_cut(env) -> None:
    _, admin, factory, user_a, _, convs = env
    async with user_session(factory, user_a) as s:
        run_id = await runs.start_run(s, user_id=user_a, conversation_id=convs[user_a], graph_version=GRAPH_VERSION)
        await runs.finish_run(s, run_id, status="failed", error="bad key sk-ant-api03-abcdefghijklmnop " + "z" * 900)
    async with admin.connect() as conn:
        err = (await conn.execute(text("SELECT error FROM agent_runs WHERE id = :i"), {"i": run_id})).scalar_one()
    assert "sk-ant" not in err and len(err) < 400


async def test_runs_and_steps_are_private_to_the_student(env) -> None:
    _, _, factory, user_a, user_b, convs = env
    async with user_session(factory, user_a) as s:
        run_id = await runs.start_run(s, user_id=user_a, conversation_id=convs[user_a], graph_version=GRAPH_VERSION)
        await runs.record_step(s, run_id, node="router")
    async with user_session(factory, user_b) as s:
        assert (await s.execute(text("SELECT count(*) FROM agent_runs"))).scalar_one() == 0
        assert (await s.execute(text("SELECT count(*) FROM agent_steps"))).scalar_one() == 0
        with pytest.raises(DBAPIError):
            await runs.start_run(s, user_id=user_a, conversation_id=None, graph_version=GRAPH_VERSION)


# --------------------------------------------------------------------------------- checkpoints


class State(TypedDict, total=False):
    topic: str
    answer: str


def build_graph(saver: Any) -> Any:
    """A tiny graph that stops for approval, like the calendar flow will."""

    def propose(state: State) -> State:
        decision = interrupt({"kind": "approve", "topic": state["topic"]})
        return {"answer": f"{state['topic']}:{decision}"}

    g = StateGraph(State)
    g.add_node("propose", propose)
    g.add_edge(START, "propose")
    g.add_edge("propose", END)
    return g.compile(checkpointer=saver)


async def test_interrupt_survives_a_new_connection_and_resumes(env) -> None:
    settings, _, _, user_a, _, convs = env
    cfg = {"configurable": {"thread_id": thread_id(user_a, convs[user_a])}}
    async with open_checkpointer(settings.database_url, user_a) as saver:
        first = await build_graph(saver).ainvoke({"topic": "viva"}, cfg)
    assert first["__interrupt__"][0].value == {"kind": "approve", "topic": "viva"}
    # A different connection (as if the API restarted) continues the same run.
    async with open_checkpointer(settings.database_url, user_a) as saver:
        graph = build_graph(saver)
        assert (await graph.aget_state(cfg)).next == ("propose",)
        done = await graph.ainvoke(Command(resume="yes"), cfg)
    assert done["answer"] == "viva:yes"


async def test_another_student_cannot_read_or_change_a_thread(env) -> None:
    settings, _, _, user_a, user_b, convs = env
    cfg_a = {"configurable": {"thread_id": thread_id(user_a, convs[user_a])}}
    async with open_checkpointer(settings.database_url, user_a) as saver:
        await build_graph(saver).ainvoke({"topic": "private"}, cfg_a)
    async with open_checkpointer(settings.database_url, user_b) as saver:
        graph = build_graph(saver)
        seen = await graph.aget_state(cfg_a)
        assert not seen.values and seen.next == ()
        # B cannot resume A's run or write into A's thread.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await graph.ainvoke({"topic": "hijack"}, cfg_a)
        async with saver.conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS n FROM checkpoints")
            assert (await cur.fetchone())["n"] == 0
    async with open_checkpointer(settings.database_url, user_a) as saver:
        assert (await build_graph(saver).aget_state(cfg_a)).values["topic"] == "private"


async def test_no_user_context_sees_no_checkpoints(env) -> None:
    settings, _, factory, user_a, _, convs = env
    async with open_checkpointer(settings.database_url, user_a) as saver:
        await build_graph(saver).ainvoke({"topic": "x"}, {"configurable": {"thread_id": thread_id(user_a, convs[user_a])}})
    async with factory() as s:
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            assert (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


async def test_deleting_a_conversation_deletes_its_saved_state(env) -> None:
    settings, admin, factory, user_a, _, convs = env
    tid = thread_id(user_a, convs[user_a])
    async with open_checkpointer(settings.database_url, user_a) as saver:
        await build_graph(saver).ainvoke({"topic": "bye"}, {"configurable": {"thread_id": tid}})
    async with admin.connect() as conn:
        before = (await conn.execute(text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"), {"t": tid})).scalar_one()
    assert before > 0
    async with user_session(factory, user_a) as s:  # the student deletes the chat
        await s.execute(text("DELETE FROM conversations WHERE id = :c"), {"c": convs[user_a]})
    async with admin.connect() as conn:
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            n = (await conn.execute(text(f"SELECT count(*) FROM {table} WHERE thread_id = :t"), {"t": tid})).scalar_one()
            assert n == 0, table


def test_migration_matches_the_installed_checkpoint_library() -> None:
    """If an upgrade of langgraph-checkpoint-postgres adds a table step, migration 0013 needs a
    follow-up migration. This fails until someone looks."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "infra/migrations/versions/0013_agents.py"
    spec = importlib.util.spec_from_file_location("m0013", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LIBRARY_MIGRATION_COUNT == len(BasePostgresSaver.MIGRATIONS)


async def test_every_checkpoint_step_is_marked_done(env) -> None:
    _, admin, *_ = env
    async with admin.connect() as conn:
        top = (await conn.execute(text("SELECT max(v) FROM checkpoint_migrations"))).scalar_one()
    assert top == len(BasePostgresSaver.MIGRATIONS) - 1


def test_dsn_conversion() -> None:
    assert psycopg_dsn("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert psycopg_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"
