"""Celery tasks."""

import asyncio
from uuid import UUID

from mindnest_api.llm import HttpLLM
from mindnest_api.retrieval import HttpModelClient
from mindnest_core.db import make_engine, make_session_factory
from mindnest_core.settings import get_settings
from mindnest_core.storage import S3Storage

from mindnest_worker.app import celery_app
from mindnest_worker.assignments import run_assignment_help
from mindnest_worker.chatfiles import read_attachment
from mindnest_worker.evaluation import run_evaluation
from mindnest_worker.pipeline import HttpEmbedder, run_ingestion
from mindnest_worker.quizzes import generate_quiz, grade_attempt


@celery_app.task(name="mindnest.ping")
def ping() -> str:
    """Smoke-test task: proves the broker, worker and result backend are wired together."""
    return "pong"


async def _ingest(material_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        await run_ingestion(
            material_id,
            owner_id,
            factory=make_session_factory(engine),
            storage=S3Storage(
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            ),
            embedder=HttpEmbedder(settings.model_service_url, settings.embed_batch_size),
            settings=settings,
        )
    finally:
        await engine.dispose()


@celery_app.task(name="mindnest.ingest_material")
def ingest_material(material_id: str, owner_id: str) -> None:
    """Read one uploaded file and make it searchable. Safe to run again for the same material."""
    asyncio.run(_ingest(UUID(material_id), UUID(owner_id)))


async def _evaluate(run_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    models = HttpModelClient(settings.model_service_url)
    llm = HttpLLM(settings.llm_timeout_seconds)
    try:
        await run_evaluation(
            run_id,
            owner_id,
            factory=make_session_factory(engine),
            models=models,
            llm=llm,
            settings=settings,
        )
    finally:
        await llm.aclose()
        await models.aclose()
        await engine.dispose()


@celery_app.task(name="mindnest.run_evaluation")
def run_evaluation_task(run_id: str, owner_id: str) -> None:
    """Score one evaluation run. Safe to deliver twice: finished questions are skipped."""
    asyncio.run(_evaluate(UUID(run_id), UUID(owner_id)))


async def _quiz(quiz_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    llm = HttpLLM(settings.llm_timeout_seconds)
    try:
        await generate_quiz(
            quiz_id, owner_id, factory=make_session_factory(engine), llm=llm, settings=settings
        )
    finally:
        await llm.aclose()
        await engine.dispose()


@celery_app.task(name="mindnest.generate_quiz")
def generate_quiz_task(quiz_id: str, owner_id: str) -> None:
    """Write the questions of one quiz. Safe to deliver twice: a finished quiz is left alone."""
    asyncio.run(_quiz(UUID(quiz_id), UUID(owner_id)))


async def _grade(attempt_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    llm = HttpLLM(settings.llm_timeout_seconds)
    try:
        await grade_attempt(
            attempt_id, owner_id, factory=make_session_factory(engine), llm=llm, settings=settings
        )
    finally:
        await llm.aclose()
        await engine.dispose()


@celery_app.task(name="mindnest.grade_attempt")
def grade_attempt_task(attempt_id: str, owner_id: str) -> None:
    """Mark the short answers of one attempt. Safe to deliver twice."""
    asyncio.run(_grade(UUID(attempt_id), UUID(owner_id)))


async def _assignment(run_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    models = HttpModelClient(settings.model_service_url)
    llm = HttpLLM(settings.llm_timeout_seconds)
    try:
        await run_assignment_help(
            run_id, owner_id, factory=make_session_factory(engine), llm=llm, models=models,
            settings=settings,
        )
    finally:
        await llm.aclose()
        await models.aclose()
        await engine.dispose()


@celery_app.task(name="mindnest.assignment_help")
def assignment_help_task(run_id: str, owner_id: str) -> None:
    """Write one piece of help for an assignment. Safe to deliver twice."""
    asyncio.run(_assignment(UUID(run_id), UUID(owner_id)))


async def _attachment(attachment_id: UUID, owner_id: UUID) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        await read_attachment(
            attachment_id, owner_id, factory=make_session_factory(engine),
            storage=S3Storage(
                settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_bucket,
            ),
            settings=settings,
        )
    finally:
        await engine.dispose()


@celery_app.task(name="mindnest.read_chat_attachment")
def read_chat_attachment_task(attachment_id: str, owner_id: str) -> None:
    """Read the text of a file attached to a chat. Safe to deliver twice."""
    asyncio.run(_attachment(UUID(attachment_id), UUID(owner_id)))
