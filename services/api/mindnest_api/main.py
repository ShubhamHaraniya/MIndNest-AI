"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mindnest_agents.guardrails import get_guardrails
from mindnest_agents.models import build_chat_model
from mindnest_agents.tracing import flush_traces, lock_down_global_tracing
from mindnest_core.db import make_engine, make_session_factory
from mindnest_core.googleoauth import GoogleClient
from mindnest_core.aisafety import PiiRedactingFilter
from mindnest_core.settings import get_settings
from mindnest_core.storage import S3Storage

from mindnest_api.calendar_gateway import CalendarGateway
from mindnest_api.errors import register_error_handlers
from mindnest_api.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from mindnest_api.jobs import CeleryQueue
from mindnest_api.llm import HttpLLM
from mindnest_api.mailer import SmtpMailer
from mindnest_api.ratelimit import RedisLimiter
from mindnest_api.retrieval import HttpModelClient
from mindnest_api.routes import (
    account,
    admin,
    assignment_workspace,
    assignments,
    auth,
    calendar_events,
    calendar_google,
    chat,
    chat_extras,
    course_tabs,
    courses,
    dashboard,
    gcal,
    group_collab,
    groups,
    google_auth,
    evaluation,
    health,
    library,
    materials,
    me,
    model_status,
    notifications,
    planner,
    providers,
    quiz_exam,
    quizzes,
    search,
    stats,
    subjects,
)
from mindnest_api.vault import DEV_SECRET


def _configure_logging() -> None:
    """Show the app's own INFO lines (chat timings) next to uvicorn's, without turning on every
    library's logging."""
    own = logging.getLogger("mindnest")
    if not own.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(PiiRedactingFilter())  # no API keys or personal data reach the logs
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        own.addHandler(handler)
        own.setLevel(logging.INFO)
        own.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Engines connect lazily, so the app starts even if the database is down;
    # /api/v1/ready reports the real state.
    _configure_logging()
    lock_down_global_tracing()  # only the masked per-run tracer may send traces
    settings = get_settings()
    if settings.environment != "development" and settings.secret_key == DEV_SECRET:
        raise RuntimeError("SECRET_KEY must be changed from its development default.")
    engine = make_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.mailer = SmtpMailer(get_settings())
    limiter = RedisLimiter(get_settings().redis_url)
    app.state.limiter = limiter
    app.state.storage = S3Storage(
        settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_bucket
    )
    app.state.queue = CeleryQueue()
    llm = HttpLLM(settings.llm_timeout_seconds)
    models = HttpModelClient(settings.model_service_url)
    app.state.llm = llm
    app.state.chat_models = build_chat_model
    google = GoogleClient(settings.google_client_id, settings.google_client_secret)
    app.state.google = google
    app.state.calendar_gateway = CalendarGateway(settings)
    if settings.guardrails_enabled:
        guard = get_guardrails(settings.guardrails_judge_timeout_seconds)
        guard.warm()  # build NeMo now so the first student's message does not wait for it
        app.state.guardrails = guard
    app.state.models = models
    try:
        yield
    finally:
        flush_traces()
        await llm.aclose()
        await models.aclose()
        await google.aclose()
        await limiter.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    development = settings.environment == "development"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        # The interactive docs and the schema describe every endpoint: handy while developing,
        # but not something to hand to the internet.
        docs_url="/api/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if development else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=not development)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(gcal.router, prefix="/api/v1")
    app.include_router(groups.router, prefix="/api/v1")
    app.include_router(group_collab.router, prefix="/api/v1")
    app.include_router(library.router, prefix="/api/v1")
    app.include_router(google_auth.router, prefix="/api/v1")
    app.include_router(me.router, prefix="/api/v1")
    app.include_router(account.router, prefix="/api/v1")
    app.include_router(subjects.router, prefix="/api/v1")
    app.include_router(materials.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(courses.router, prefix="/api/v1")
    app.include_router(course_tabs.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(providers.router, prefix="/api/v1")
    app.include_router(model_status.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(chat_extras.router, prefix="/api/v1")
    app.include_router(evaluation.router, prefix="/api/v1")
    app.include_router(assignments.router, prefix="/api/v1")
    app.include_router(assignment_workspace.router, prefix="/api/v1")
    app.include_router(planner.router, prefix="/api/v1")
    app.include_router(calendar_events.router, prefix="/api/v1")
    app.include_router(calendar_google.router, prefix="/api/v1")
    app.include_router(quizzes.router, prefix="/api/v1")
    app.include_router(quiz_exam.router, prefix="/api/v1")
    return app


app = create_app()
