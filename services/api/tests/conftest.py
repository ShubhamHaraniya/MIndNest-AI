"""Shared fixtures for API tests that need a migrated Postgres.

These tests skip themselves when the database is unreachable or migration 0005 has not been
applied. To run them: `docker compose up -d postgres redis`, `alembic upgrade head`, `pytest`.

All requests go through ONE entered TestClient. A client that is not entered would start a new
event loop per request, which breaks asyncpg's pooled connections. Different "browsers" are
simulated by sending each actor's session cookie by hand and keeping the shared cookie jar empty.
"""

import asyncio
import json
import random
import re
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from fastapi.testclient import TestClient
from mindnest_api.deps import (
    get_calendar_gateway,
    get_chat_models,
    get_google,
    get_limiter,
    get_llm,
    get_mailer,
    get_models,
    get_queue,
    get_storage,
)
from mindnest_api.calendar_gateway import CalendarGateway
from mindnest_api.llm import ChatMessage, LLMError
from mindnest_api.main import create_app
from mindnest_core.db import make_engine, make_session_factory
from mindnest_core.googlecalendar import CalendarApiError
from mindnest_core.googleoauth import GoogleError
from mindnest_core.settings import get_settings
from mindnest_core.storage import MemoryStorage
from mindnest_worker.assignments import run_assignment_help
from mindnest_worker.evaluation import run_evaluation
from mindnest_worker.quizzes import generate_quiz as run_generate_quiz
from mindnest_worker.quizzes import grade_attempt as run_grade_attempt
from mindnest_worker.pipeline import DeterministicEmbedder, Embedder, run_ingestion
from sqlalchemy import text

TEST_DOMAIN = "mindnest-tests.dev"
PASSWORD = "correct horse battery"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

    def last_token(self, to: str) -> str:
        for message in reversed(self.sent):
            if message["to"] == to:
                match = re.search(r"token=([\w-]+)", message["body"])
                assert match, "email has no token link"
                return match.group(1)
        raise AssertionError(f"no email was sent to {to}")

    def count(self, to: str) -> int:
        return sum(1 for message in self.sent if message["to"] == to)


class RecordingQueue:
    """Stands in for Celery: remembers what was enqueued instead of running it."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str]] = []
        self.eval_jobs: list[tuple[str, str]] = []
        self.quiz_jobs: list[tuple[str, str]] = []
        self.grade_jobs: list[tuple[str, str]] = []
        self.assignment_jobs: list[tuple[str, str]] = []
        self.attachment_jobs: list[tuple[str, str]] = []

    async def enqueue_ingestion(self, material_id: Any, owner_id: Any) -> None:
        self.jobs.append((str(material_id), str(owner_id)))

    async def enqueue_evaluation(self, run_id: Any, owner_id: Any) -> None:
        self.eval_jobs.append((str(run_id), str(owner_id)))

    async def enqueue_quiz_generation(self, quiz_id: Any, owner_id: Any) -> None:
        self.quiz_jobs.append((str(quiz_id), str(owner_id)))

    async def enqueue_attempt_grading(self, attempt_id: Any, owner_id: Any) -> None:
        self.grade_jobs.append((str(attempt_id), str(owner_id)))

    async def enqueue_assignment_run(self, run_id: Any, owner_id: Any) -> None:
        self.assignment_jobs.append((str(run_id), str(owner_id)))

    async def enqueue_chat_attachment(self, attachment_id: Any, owner_id: Any) -> None:
        self.attachment_jobs.append((str(attachment_id), str(owner_id)))


class FakeCalendarApi:
    """Stands in for the Google Calendar API: remembers the calls and keeps events in a dict.

    Like Google it lets the caller choose an event's id, answers 409 for an id already used
    (also after the event was deleted: Google keeps deleted ids) and gives each event a link."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calendars: list[str] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.calendar_of: dict[str, str] = {}  # event id -> the calendar it was added to
        self.deleted_ids: set[str] = set()
        self.calls: list[tuple[str, str]] = []  # (action, event id or calendar name)
        self.deleted_calendars: list[str] = []
        self.fail: dict[str, int] = {}  # action -> status code to answer with
        self._n = 0

    def _maybe_fail(self, action: str) -> None:
        if action in self.fail:
            raise CalendarApiError(self.fail[action])

    @staticmethod
    def _shown(event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return {**body, "id": event_id, "status": "confirmed",
                "htmlLink": f"https://calendar.google.com/calendar/event?eid={event_id}"}

    async def create_calendar(self, token: str, name: str) -> str:
        self.calls.append(("create_calendar", name))
        self._maybe_fail("create_calendar")
        self.calendars.append(name)
        return f"cal-{len(self.calendars)}@group.calendar.google.com"

    async def create_event(self, token: str, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self._maybe_fail("insert")
        event_id = str(body.get("id") or "")
        if event_id and (event_id in self.events or event_id in self.deleted_ids):
            self.calls.append(("insert_duplicate", event_id))
            raise CalendarApiError(409, "duplicate")
        if not event_id:
            self._n += 1
            event_id = f"ev{self._n}"
        self.calls.append(("insert", event_id))
        stored = {k: v for k, v in body.items() if k != "id"}
        self.events[event_id] = stored
        self.calendar_of[event_id] = calendar_id
        return self._shown(event_id, stored)

    async def insert_event(self, token: str, calendar_id: str, body: dict[str, Any]) -> str:
        return str((await self.create_event(token, calendar_id, body))["id"])

    async def get_event(self, token: str, calendar_id: str, event_id: str) -> dict[str, Any]:
        self.calls.append(("get", event_id))
        self._maybe_fail("get")
        if event_id in self.events:
            return self._shown(event_id, self.events[event_id])
        if event_id in self.deleted_ids:
            return {"id": event_id, "status": "cancelled"}
        raise CalendarApiError(404)

    async def list_events(
        self, token: str, calendar_id: str, time_min: str, time_max: str, limit: int
    ) -> list[dict[str, Any]]:
        self.calls.append(("list", calendar_id))
        self._maybe_fail("list")
        shown = [self._shown(i, b) for i, b in self.events.items()]
        shown.sort(key=lambda e: str(e["start"].get("dateTime") or e["start"].get("date")))
        return shown[:limit]

    async def patch_event(self, token: str, calendar_id: str, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("patch", event_id))
        self._maybe_fail("patch")
        if event_id not in self.events:
            raise CalendarApiError(404)
        self.events[event_id] = {k: v for k, v in body.items() if k != "id"}
        return self._shown(event_id, self.events[event_id])

    async def delete_event(self, token: str, calendar_id: str, event_id: str) -> None:
        self.calls.append(("delete", event_id))
        self._maybe_fail("delete")
        if event_id not in self.events:
            raise CalendarApiError(404)
        del self.events[event_id]
        self.deleted_ids.add(event_id)

    async def delete_calendar(self, token: str, calendar_id: str) -> None:
        self.calls.append(("delete_calendar", calendar_id))
        self.deleted_calendars.append(calendar_id)

    async def aclose(self) -> None:
        return None


class NoLimit:
    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        return None


class FakeLLM:
    """Stands in for the AI providers: replays `pieces`, or raises `error` after `fail_after`
    pieces, and remembers every call so tests can inspect the prompt."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        # When set, decides the reply: responder(system, messages) -> text pieces.
        self.responder: Callable[[str, list[ChatMessage]], list[str]] | None = None
        self.pieces: list[str] = ["Hello ", "world [1]"]
        self.error: str | None = None
        self.fail_after = 0
        self.calls: list[dict[str, Any]] = []
        # The orchestrator: which agent(s) it picks, as a name or a list of names, or raw reply text.
        self.route: str | list[str] | dict[str, Any] = "study"
        self.router_calls: list[dict[str, Any]] = []
        self.error_in_router = False
        # The guardrail judge (a second opinion on risky messages) is answered apart from the agents.
        self.judge_calls: list[dict[str, Any]] = []
        self.judge_reply: str | None = '{"label": "fine"}'  # None makes the judge call fail
        self.tool_script: list[list[dict[str, Any]] | None] = []
        self.tools_seen: list[list[str]] = []

    def router_reply(self) -> str:
        if isinstance(self.route, dict):
            return json.dumps(self.route)
        if isinstance(self.route, str) and self.route.lstrip().startswith("{"):
            return self.route
        names = [self.route] if isinstance(self.route, str) else self.route
        return json.dumps({"steps": [{"agent": n, "task": f"{n} task", "query": ""} for n in names], "reason": "test"})

    async def list_models(self, provider: str, api_key: str) -> list[str]:
        if self.error:
            raise LLMError(self.error)
        return ["model-a", "model-b"]

    async def stream(
        self,
        provider: str,
        api_key: str,
        model: str,
        system: str,
        messages: list[ChatMessage],
    ) -> AsyncGenerator[str, None]:
        self.calls.append(
            {"provider": provider, "api_key": api_key, "model": model, "system": system,
             "messages": messages}
        )
        pieces = self.responder(system, messages) if self.responder else self.pieces
        for index, piece in enumerate(pieces):
            if self.error and index >= self.fail_after:
                raise LLMError(self.error)
            yield piece
        if self.error and self.fail_after >= len(pieces):
            raise LLMError(self.error)


class FakeChatModel(BaseChatModel):
    """A LangChain chat model that plays the FakeLLM script. Calls from the orchestrator's router
    are answered from `llm.route` and kept apart from `llm.calls`, so tests that look at "the last
    call" see the agent's answer. Tool calls come from `llm.tool_script` (one entry per model
    turn made while tools are bound: a list of {"name", "args"}, or None to answer in text)."""

    llm: Any
    provider: str = "openai"
    model_name: str = "fake"
    api_key: str = ""
    bound: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":  # type: ignore[override]
        return self.model_copy(update={"bound": [getattr(t, "name", str(t)) for t in tools]})

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        parts = [c.message.content async for c in self._astream(messages)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="".join(map(str, parts))))])

    async def _astream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any):  # type: ignore[no-untyped-def]
        system = ""
        turns: list[ChatMessage] = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system = str(m.content)
            elif isinstance(m, HumanMessage):
                turns.append(ChatMessage("user", str(m.content)))
            elif isinstance(m, ToolMessage):
                turns.append(ChatMessage("user", f"TOOL RESULT ({m.name}): {m.content}"))
            elif isinstance(m, AIMessage) and not m.tool_calls:
                turns.append(ChatMessage("assistant", str(m.content)))
        if system.startswith("You are a safety classifier for MindNest AI"):
            self.llm.judge_calls.append({"system": system, "messages": turns})
            if self.llm.judge_reply is None:
                raise LLMError("provider_unavailable")
            yield ChatGenerationChunk(message=AIMessageChunk(content=self.llm.judge_reply))
            return
        if system.startswith("You are the orchestrator"):
            self.llm.router_calls.append({"system": system, "messages": turns})
            if self.llm.error and self.llm.error_in_router:
                raise LLMError(self.llm.error)
            yield ChatGenerationChunk(message=AIMessageChunk(content=self.llm.router_reply()))
            return
        if self.bound and self.llm.tool_script:
            batch = self.llm.tool_script.pop(0)
            if batch:
                chunks = [
                    {"name": c["name"], "args": json.dumps(c.get("args", {})), "id": f"call_{i}_{len(self.llm.calls)}", "index": i}
                    for i, c in enumerate(batch)
                ]
                self.llm.calls.append({"provider": self.provider, "api_key": self.api_key, "model": self.model_name,
                                       "system": system, "messages": turns, "tools": self.bound})
                yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
                return
        self.llm.tools_seen.append(list(self.bound))
        async for piece in self.llm.stream(self.provider, self.api_key, self.model_name, system, turns):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        self.llm.calls[-1]["tools"] = list(self.bound)


class FakeModels:
    """Embeds with the hash-based test embedder and reranks by shared words."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await DeterministicEmbedder(get_settings().embedding_dim).embed(texts)
        return result.vectors

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        words = set(query.lower().split())
        return [float(len(words & set(p.lower().split()))) for p in passages]


class FakeGoogle:
    """Stands in for Google's token endpoint: hands back whatever identity token the test set."""

    client_id = "test-client-id.apps.googleusercontent.com"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.token = ""
        self.fail = False
        self.calls: list[dict[str, str]] = []
        # What Google says when the student connects Calendar (a separate consent from sign-in).
        self.scope = ""
        self.refresh_token: str | None = "1//fake"
        self.refresh_fail = False
        self.revoked: list[str] = []

    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        self.calls.append({"code": code, "verifier": verifier, "redirect_uri": redirect_uri})
        if self.fail:
            raise GoogleError("Google refused the request (400)")
        tokens: dict[str, Any] = {"id_token": self.token, "access_token": "ya29.fake", "scope": self.scope}
        if self.refresh_token:
            tokens["refresh_token"] = self.refresh_token
        return tokens

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        if self.refresh_fail:
            raise GoogleError("Google refused the request (400)", permanent=True)
        return {"access_token": "ya29.refreshed"}

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)

    async def aclose(self) -> None:
        return None


async def _not_ready_reason() -> str | None:
    engine = make_engine(get_settings().migration_database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM revision_cards LIMIT 1"))
        return None
    except Exception as exc:
        return str(exc).splitlines()[0]
    finally:
        await engine.dispose()


async def _delete_test_users() -> None:
    engine = make_engine(get_settings().migration_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM users WHERE email LIKE :pattern"), {"pattern": f"%@{TEST_DOMAIN}"}
            )
    finally:
        await engine.dispose()


class Actor:
    """One browser: an optional session token plus a thin wrapper over the shared client."""

    def __init__(self, client: TestClient, token: str | None = None) -> None:
        self._client = client
        self.token = token
        self.email = ""
        self.password = PASSWORD
        self.id = ""

    def request(self, method: str, path: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["cookie"] = f"{get_settings().session_cookie_name}={self.token}"
        try:
            return self._client.request(method, f"/api/v1{path}", headers=headers, **kwargs)
        finally:
            self._client.cookies.clear()

    def get(self, path: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self.request("DELETE", path, **kwargs)


@pytest.fixture
def owner_sql() -> Callable[..., list[dict[str, Any]]]:
    """Run a query as the table owner (row-level security does not apply), to look at what the
    app wrote. Returns a list of dict rows."""

    def _run(sql: str, **params: Any) -> list[dict[str, Any]]:
        async def go() -> list[dict[str, Any]]:
            engine = make_engine(get_settings().migration_database_url)
            try:
                async with engine.connect() as conn:
                    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]
            finally:
                await engine.dispose()

        return asyncio.run(go())

    return _run


@pytest.fixture(scope="session")
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture(scope="session")
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture(scope="session")
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture(scope="session")
def _llm_singleton() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def llm(_llm_singleton: FakeLLM) -> FakeLLM:
    _llm_singleton.reset()
    return _llm_singleton


@pytest.fixture(scope="session")
def _google_singleton() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture(autouse=True)
def _google_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests start with Google switched off, even when the developer's own .env holds real Google
    credentials. The `google` fixture below switches it on for the tests that want it."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")


@pytest.fixture
def google(_google_singleton: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    """Google sign-in switched on for one test, talking to the fake."""
    _google_singleton.reset()
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", _google_singleton.client_id)
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    return _google_singleton


@pytest.fixture(scope="session")
def _calendar_singleton() -> FakeCalendarApi:
    return FakeCalendarApi()


@pytest.fixture
def calendar_api(_calendar_singleton: FakeCalendarApi) -> FakeCalendarApi:
    _calendar_singleton.reset()
    return _calendar_singleton


@pytest.fixture
def link_google() -> Callable[..., None]:
    """Give a student a saved Google Calendar permission (what finishing the connect flow stores),
    without going through the consent screens, which test_gcal covers."""
    from mindnest_api.vault import encrypt
    from mindnest_core.googlecalendar import SCOPE

    def _link(user: "Actor", calendar_id: str | None = "cal-test") -> None:
        async def go() -> None:
            engine = make_engine(get_settings().migration_database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO google_calendar_links (user_id, refresh_token_enc, scope, calendar_id) "
                            "VALUES (:u, :t, :s, :c)"
                        ),
                        {"u": uuid.UUID(user.id), "t": encrypt(get_settings().secret_key, "1//fake"),
                         "s": SCOPE, "c": calendar_id},
                    )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _link


@pytest.fixture(scope="session")
def calendar_server_url(_calendar_singleton: FakeCalendarApi, _google_singleton: FakeGoogle) -> Iterator[str]:
    """The real calendar MCP server, over real HTTP on a free local port, in its own thread (and
    so its own event loop and database connections). Only Google itself is replaced by fakes."""
    import socket
    import threading

    import uvicorn
    from mindnest_calendar_mcp.server import CalendarService, create_app

    reason = asyncio.run(_not_ready_reason())
    if reason:
        pytest.skip(f"migrated database not available (run alembic upgrade head): {reason}")
    settings = get_settings()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    started = threading.Event()
    box: dict[str, Any] = {}

    async def serve() -> None:
        engine = make_engine(settings.database_url)
        service = CalendarService(
            settings, make_session_factory(engine), _google_singleton, _calendar_singleton  # type: ignore[arg-type]
        )
        server = uvicorn.Server(
            uvicorn.Config(create_app(service), host="127.0.0.1", port=port, log_level="warning")
        )
        box["server"], box["service"] = server, service
        task = asyncio.create_task(server.serve())
        while not server.started and not task.done():
            await asyncio.sleep(0.02)
        started.set()
        await task
        await engine.dispose()

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    assert started.wait(20), "the calendar server did not start"
    yield f"http://127.0.0.1:{port}/mcp"
    box["server"].should_exit = True
    thread.join(10)


@pytest.fixture(scope="session")
def app(
    mailer: FakeMailer,
    storage: MemoryStorage,
    queue: RecordingQueue,
    _llm_singleton: FakeLLM,
    _google_singleton: FakeGoogle,
    calendar_server_url: str,
) -> Iterator[FastAPI]:
    reason = asyncio.run(_not_ready_reason())
    if reason:
        pytest.skip(f"migrated database not available (run alembic upgrade head): {reason}")
    application = create_app()
    application.dependency_overrides[get_mailer] = lambda: mailer
    application.dependency_overrides[get_limiter] = lambda: NoLimit()
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_queue] = lambda: queue
    application.dependency_overrides[get_llm] = lambda: _llm_singleton
    application.dependency_overrides[get_chat_models] = lambda: (
        lambda provider, model, api_key, **kw: FakeChatModel(
            llm=_llm_singleton, provider=provider, model_name=model, api_key=api_key
        )
    )
    application.dependency_overrides[get_models] = lambda: FakeModels()
    application.dependency_overrides[get_google] = lambda: _google_singleton
    gateway = CalendarGateway(get_settings(), url=calendar_server_url)
    application.dependency_overrides[get_calendar_gateway] = lambda: gateway
    yield application
    asyncio.run(_delete_test_users())


@pytest.fixture(scope="session")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:  # entering runs the lifespan
        yield test_client


@pytest.fixture
def anon(client: TestClient) -> Actor:
    return Actor(client)


@pytest.fixture
def make_user(client: TestClient) -> Callable[..., Actor]:
    def _make(display_name: str = "Test Student") -> Actor:
        email = f"{uuid.uuid4().hex[:12]}@{TEST_DOMAIN}"
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": PASSWORD, "display_name": display_name},
        )
        client.cookies.clear()
        assert response.status_code == 201, response.text
        actor = Actor(client, response.cookies.get(get_settings().session_cookie_name))
        actor.email = email
        actor.id = response.json()["id"]
        return actor

    return _make


@pytest.fixture
def ingest(storage: MemoryStorage) -> Callable[..., None]:
    """Run the real ingestion pipeline for one material, in this process.

    It uses its own database engine (and event loop), the in-memory storage the API wrote
    to, and a fake embedder unless a different one is given.
    """

    def _run(material_id: str, owner_id: str, embedder: Embedder | None = None) -> None:
        async def go() -> None:
            settings = get_settings()
            engine = make_engine(settings.database_url)
            try:
                await run_ingestion(
                    uuid.UUID(material_id),
                    uuid.UUID(owner_id),
                    factory=make_session_factory(engine),
                    storage=storage,
                    embedder=embedder or DeterministicEmbedder(settings.embedding_dim),
                    settings=settings,
                )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _run


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def evaluate(_llm_singleton: FakeLLM) -> Callable[..., None]:
    """Run the real evaluation runner for one run, in this process (no Celery, no waiting)."""

    def _run(run_id: str, owner_id: str, models: Any = None) -> None:
        async def go() -> None:
            settings = get_settings()
            engine = make_engine(settings.database_url)
            try:
                await run_evaluation(
                    uuid.UUID(run_id),
                    uuid.UUID(owner_id),
                    factory=make_session_factory(engine),
                    models=models or FakeModels(),
                    llm=_llm_singleton,
                    settings=settings,
                    sleep=_no_sleep,
                    backoff=(0.0, 0.0),
                )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _run


@pytest.fixture
def generate_quiz(_llm_singleton: FakeLLM) -> Callable[..., None]:
    """Run the real quiz writer for one quiz, in this process (no Celery, no waiting)."""

    def _run(quiz_id: str, owner_id: str, seed: int = 7) -> None:
        async def go() -> None:
            settings = get_settings()
            engine = make_engine(settings.database_url)
            try:
                await run_generate_quiz(
                    uuid.UUID(quiz_id),
                    uuid.UUID(owner_id),
                    factory=make_session_factory(engine),
                    llm=_llm_singleton,
                    settings=settings,
                    sleep=_no_sleep,
                    backoff=(0.0, 0.0),
                    rng=random.Random(seed),
                )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _run


@pytest.fixture
def grade_attempt(_llm_singleton: FakeLLM) -> Callable[..., None]:
    """Run the real short-answer marker for one attempt, in this process."""

    def _run(attempt_id: str, owner_id: str) -> None:
        async def go() -> None:
            settings = get_settings()
            engine = make_engine(settings.database_url)
            try:
                await run_grade_attempt(
                    uuid.UUID(attempt_id),
                    uuid.UUID(owner_id),
                    factory=make_session_factory(engine),
                    llm=_llm_singleton,
                    settings=settings,
                    sleep=_no_sleep,
                    backoff=(0.0, 0.0),
                )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _run


@pytest.fixture
def assignment_help(_llm_singleton: FakeLLM) -> Callable[..., None]:
    """Run the real assignment helper for one run, in this process."""

    def _run(run_id: str, owner_id: str) -> None:
        async def go() -> None:
            settings = get_settings()
            engine = make_engine(settings.database_url)
            try:
                await run_assignment_help(
                    uuid.UUID(run_id),
                    uuid.UUID(owner_id),
                    factory=make_session_factory(engine),
                    llm=_llm_singleton,
                    models=FakeModels(),
                    settings=settings,
                    sleep=_no_sleep,
                    backoff=(0.0, 0.0),
                )
            finally:
                await engine.dispose()

        asyncio.run(go())

    return _run
