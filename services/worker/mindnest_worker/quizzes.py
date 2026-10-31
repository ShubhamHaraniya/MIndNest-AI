"""Making quizzes from a student's own materials and marking their short answers.

Both jobs use the student's own AI key (the same one chat uses) and run in the background, so a
slow or rate-limited provider never holds a web request open. A job can be delivered twice: a quiz
that is already generated, or an attempt that is already completed, is left alone.
"""

import asyncio
import json
import logging
import math
import random
from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from mindnest_api.llm import LLM, LLMError
from mindnest_core.aisafety import prepare_untrusted, prepare_user_text
from mindnest_core.db import as_json, user_session
from mindnest_core.quizlogic import (
    MAX_QUESTIONS,
    general_prompt,
    general_system,
    PASSAGES_PER_CALL,
    SNIPPET_CHARS,
    distribute_types,
    generate_prompt,
    generate_system,
    grade_prompt,
    grade_system,
    interleave,
    looks_like_prose,
    parse_generated_report,
    parse_grade,
)
from mindnest_core.quizcheck import QuestionChecker
from mindnest_core.quizstore import finalize_attempt
from mindnest_core.redact import redact
from mindnest_core.safetystore import record_prepared
from mindnest_core.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mindnest_worker.llmcalls import RATE_LIMIT_BACKOFF, Sleep
from mindnest_worker.llmcalls import JobFailed as QuizFailed
from mindnest_worker.llmcalls import collect as _collect
from mindnest_worker.llmcalls import key_for as _key_for

logger = logging.getLogger("mindnest.quizzes")

type SessionFactory = async_sessionmaker[AsyncSession]

CANDIDATE_CHUNKS = 600
EXTRA_CALLS = 3


# ------------------------------------------------------------------------------ generating


async def generate_quiz(
    quiz_id: UUID, owner_id: UUID, *, factory: SessionFactory, llm: LLM, settings: Settings,
    sleep: Sleep = asyncio.sleep, backoff: tuple[float, ...] = RATE_LIMIT_BACKOFF,
    rng: random.Random | None = None,
) -> None:
    try:
        await _generate(quiz_id, owner_id, factory, llm, settings, sleep, backoff, rng or random.Random())
    except QuizFailed as exc:
        await _fail_quiz(factory, owner_id, quiz_id, exc.code)
    except Exception as exc:
        logger.error("Quiz %s failed: %s", quiz_id, redact(f"{type(exc).__name__}: {exc}"))
        await _fail_quiz(factory, owner_id, quiz_id, "internal")


async def _fail_quiz(factory: SessionFactory, owner_id: UUID, quiz_id: UUID, code: str) -> None:
    async with user_session(factory, owner_id) as session:
        await session.execute(
            text(
                "UPDATE quizzes SET status = 'failed', error = :e, finished_at = now() "
                "WHERE id = :q AND status IN ('queued', 'generating')"
            ),
            {"q": quiz_id, "e": code},
        )


async def _generate(
    quiz_id: UUID, owner_id: UUID, factory: SessionFactory, llm: LLM, settings: Settings,
    sleep: Sleep, backoff: tuple[float, ...], rng: random.Random,
) -> None:
    async with user_session(factory, owner_id) as session:
        quiz = (
            (
                await session.execute(
                    text("SELECT subject_id, language, config, status FROM quizzes WHERE id = :q"),
                    {"q": quiz_id},
                )
            )
            .mappings()
            .first()
        )
        if quiz is None or quiz["status"] not in ("queued", "generating"):
            return
        cfg: dict[str, Any] = as_json(quiz["config"]) or {}
        provider, default_model, api_key = await _key_for(session, settings, cfg.get("provider"))
        model = cfg.get("model") or default_model
        mask = await _mask_setting(session, owner_id)
        await session.execute(text("UPDATE quizzes SET status = 'generating' WHERE id = :q"), {"q": quiz_id})
        if cfg.get("basis") == "general":
            rows: list[Any] = []  # no notes involved: the questions come from the AI's own knowledge
        else:
            chunk_ids = [c for c in (cfg.get("chunk_ids") or []) if isinstance(c, str)][:CANDIDATE_CHUNKS]
            # A topic quiz uses the passages the chat already found for that topic; otherwise a
            # random sample of the whole subject.
            rows = list(
                (
                    await session.execute(
                        text(
                            "SELECT c.id, c.material_id, c.page, c.text, m.filename "
                            "FROM chunks c JOIN materials m ON m.id = c.material_id "
                            "WHERE c.is_active AND m.deleted_at IS NULL AND m.status = 'ready' "
                            "AND (c.id = ANY(CAST(:ids AS uuid[])) OR "
                            "(CAST(:ids AS uuid[]) IS NULL AND c.subject_id = :s)) "
                            "ORDER BY random() LIMIT :n"
                        ),
                        {"s": quiz["subject_id"], "n": CANDIDATE_CHUNKS, "ids": chunk_ids or None},
                    )
                )
                .mappings()
                .all()
            )

    count = max(1, min(int(cfg.get("count") or 10), MAX_QUESTIONS))
    language = str(quiz["language"])
    if cfg.get("basis") == "general":
        await _generate_general(
            quiz_id, owner_id, cfg, count, language, factory, llm, (provider, model, api_key),
            mask, sleep, backoff, rng,
        )
        return

    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if looks_like_prose(row["text"]):
            groups[row["material_id"]].append(dict(row))
    pool = interleave(list(groups.values()), rng)
    if not pool:
        raise QuizFailed("no_materials")

    topic = prepare_user_text(str(cfg.get("topic") or ""), mask_optional=mask).text or None
    system = generate_system(language, str(cfg.get("difficulty") or "medium"), topic)
    needed = distribute_types(count, cfg.get("types") or ["mcq"], rng)
    max_calls = math.ceil(count / PASSAGES_PER_CALL) + EXTRA_CALLS

    made: list[tuple[Any, dict[str, Any]]] = []  # (generated question, chunk row)
    checker = QuestionChecker()  # one per quiz, so a repeated question is caught across calls
    rejected: Counter[str] = Counter()
    pii: Counter[str] = Counter()
    injections = hidden = 0
    used = calls = 0
    last_error: str | None = None
    while len(made) < count and used < len(pool) and calls < max_calls:
        batch = pool[used : used + min(PASSAGES_PER_CALL, count - len(made))]
        used += len(batch)
        plan = {i: needed[i] for i in range(len(batch))}
        plan = {i + 1: kind for i, kind in plan.items()}
        calls += 1
        # Passages go to the provider as data: hidden characters removed, instruction-like text
        # quoted, personal data masked. The stored source snippet below stays as written.
        safe = [prepare_untrusted(c["text"], mask_optional=mask) for c in batch]
        for entry in safe:
            pii.update(entry.pii)
            injections += len(entry.injection)
            hidden += entry.hidden_removed
        try:
            reply = await _collect(
                llm, provider, api_key, model, system,
                generate_prompt([entry.text for entry in safe], [plan[i + 1] for i in range(len(batch))]),
                sleep, backoff,
            )
        except LLMError as exc:
            if exc.code == "invalid_key":
                raise QuizFailed("invalid_key") from exc
            last_error = exc.code
            continue
        report = parse_generated_report(reply, plan, rng, checker)
        rejected.update(report.rejected)
        for item in report.questions:
            made.append((item, batch[item.passage - 1]))
            needed.remove(item.qtype)

    if not made:
        raise QuizFailed(last_error or "generation_failed")

    async with user_session(factory, owner_id) as session:
        for position, (item, chunk) in enumerate(made, start=1):
            source = {
                "filename": chunk["filename"], "page": chunk["page"],
                "chunk_id": str(chunk["id"]), "text": chunk["text"][:SNIPPET_CHARS],
            }
            await session.execute(
                text(
                    "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, options, "
                    "answer, explanation, source) VALUES (:q, :u, :p, :t, :pr, CAST(:o AS jsonb), "
                    ":a, :e, CAST(:s AS jsonb))"
                ),
                {
                    "q": quiz_id, "u": owner_id, "p": position, "t": item.qtype, "pr": item.prompt,
                    "o": json.dumps(item.options, ensure_ascii=False) if item.options else None,
                    "a": item.answer, "e": item.explanation or None,
                    "s": json.dumps(source, ensure_ascii=False),
                },
            )
        await session.execute(
            text(
                "UPDATE quizzes SET status = 'ready', question_count = :n, error = NULL, "
                "finished_at = now(), config = config || CAST(:rej AS jsonb) WHERE id = :q"
            ),
            {"q": quiz_id, "n": len(made), "rej": rejected_json(rejected)},
        )
        await record_prepared(session, owner_id, "quiz", pii=pii, injections=injections, hidden=hidden)


async def _generate_general(
    quiz_id: UUID, owner_id: UUID, cfg: dict[str, Any], count: int, language: str,
    factory: SessionFactory, llm: LLM, credentials: tuple[str, str, str], mask: bool,
    sleep: Sleep, backoff: tuple[float, ...], rng: random.Random,
) -> None:
    """A quiz with no notes behind it: the AI writes questions about the subject and topic from
    its own knowledge. These questions have no source, and the quiz is labelled accordingly."""
    provider, model, api_key = credentials
    subject_text = prepare_user_text(str(cfg.get("subject_name") or ""), mask_optional=mask)
    topic_text = prepare_user_text(str(cfg.get("topic") or ""), mask_optional=mask)
    if not (subject_text.text.strip() or topic_text.text.strip()):
        raise QuizFailed("generation_failed")
    pii: Counter[str] = Counter(subject_text.pii) + Counter(topic_text.pii)
    hidden = subject_text.hidden_removed + topic_text.hidden_removed
    system = general_system(language, str(cfg.get("difficulty") or "medium"))
    needed = distribute_types(count, cfg.get("types") or ["mcq"], rng)
    batch_size = PASSAGES_PER_CALL
    max_calls = math.ceil(count / batch_size) + EXTRA_CALLS

    made: list[Any] = []
    calls = 0
    checker = QuestionChecker()
    rejected: Counter[str] = Counter()
    last_error: str | None = None
    while len(made) < count and calls < max_calls:
        size = min(batch_size, count - len(made))
        plan_types = needed[:size]
        plan = {i + 1: kind for i, kind in enumerate(plan_types)}
        calls += 1
        try:
            reply = await _collect(
                llm, provider, api_key, model, system,
                general_prompt(
                    subject_text.text or topic_text.text, topic_text.text or None, plan_types,
                    [q.prompt for q in made],
                ),
                sleep, backoff,
            )
        except LLMError as exc:
            if exc.code == "invalid_key":
                raise QuizFailed("invalid_key") from exc
            last_error = exc.code
            continue
        report = parse_generated_report(reply, plan, rng, checker)
        rejected.update(report.rejected)
        for item in report.questions:
            made.append(item)
            needed.remove(item.qtype)
    if not made:
        raise QuizFailed(last_error or "generation_failed")

    async with user_session(factory, owner_id) as session:
        for position, item in enumerate(made, start=1):
            await session.execute(
                text(
                    "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, options, "
                    "answer, explanation, source) VALUES (:q, :u, :p, :t, :pr, CAST(:o AS jsonb), "
                    ":a, :e, NULL)"
                ),
                {
                    "q": quiz_id, "u": owner_id, "p": position, "t": item.qtype, "pr": item.prompt,
                    "o": json.dumps(item.options, ensure_ascii=False) if item.options else None,
                    "a": item.answer, "e": item.explanation or None,
                },
            )
        await session.execute(
            text(
                "UPDATE quizzes SET status = 'ready', question_count = :n, error = NULL, "
                "finished_at = now(), config = config || CAST(:rej AS jsonb) WHERE id = :q"
            ),
            {"q": quiz_id, "n": len(made), "rej": rejected_json(rejected)},
        )
        await record_prepared(session, owner_id, "quiz", pii=pii, injections=0, hidden=hidden)


def rejected_json(rejected: Counter[str]) -> str:
    """What the quiz checks threw away, stored in the quiz's config so the screen can say so
    honestly: {"rejected": {"count": 2, "reasons": {"duplicate": 1, ...}}}."""
    return json.dumps(
        {"rejected": {"count": sum(rejected.values()), "reasons": dict(rejected)}}, ensure_ascii=False
    )


async def _mask_setting(session: AsyncSession, owner_id: UUID) -> bool:
    value = (
        await session.execute(text("SELECT mask_personal_data FROM users WHERE id = :u"), {"u": owner_id})
    ).scalar_one_or_none()
    return True if value is None else bool(value)


# ------------------------------------------------------------------------------ marking


async def grade_attempt(
    attempt_id: UUID, owner_id: UUID, *, factory: SessionFactory, llm: LLM, settings: Settings,
    sleep: Sleep = asyncio.sleep, backoff: tuple[float, ...] = RATE_LIMIT_BACKOFF,
) -> None:
    """Mark the short answers of one submitted attempt, then complete it.

    If the AI marker is unavailable the short answers stay unmarked and the attempt still
    completes, with the marked questions only. The student is told which were not marked.
    """
    try:
        await _grade(attempt_id, owner_id, factory, llm, settings, sleep, backoff)
    except Exception as exc:
        logger.error("Marking attempt %s failed: %s", attempt_id, redact(f"{type(exc).__name__}: {exc}"))
    async with user_session(factory, owner_id) as session:
        status = (
            await session.execute(text("SELECT status FROM quiz_attempts WHERE id = :a"), {"a": attempt_id})
        ).scalar_one_or_none()
        if status == "grading":
            await finalize_attempt(session, attempt_id, owner_id)


async def _grade(
    attempt_id: UUID, owner_id: UUID, factory: SessionFactory, llm: LLM, settings: Settings,
    sleep: Sleep, backoff: tuple[float, ...],
) -> None:
    async with user_session(factory, owner_id) as session:
        attempt = (
            (
                await session.execute(
                    text(
                        "SELECT t.status, z.language FROM quiz_attempts t "
                        "JOIN quizzes z ON z.id = t.quiz_id WHERE t.id = :a"
                    ),
                    {"a": attempt_id},
                )
            )
            .mappings()
            .first()
        )
        if attempt is None or attempt["status"] != "grading":
            return
        pending = (
            (
                await session.execute(
                    text(
                        "SELECT a.id, a.response, q.prompt, q.answer, q.source "
                        "FROM quiz_answers a JOIN quiz_questions q ON q.id = a.question_id "
                        "WHERE a.attempt_id = :a AND a.score IS NULL AND q.qtype = 'short' "
                        "AND a.response <> '' ORDER BY q.position"
                    ),
                    {"a": attempt_id},
                )
            )
            .mappings()
            .all()
        )
        if not pending:
            return
        mask = await _mask_setting(session, owner_id)
        try:
            provider, model, api_key = await _key_for(session, settings, None)
        except QuizFailed:
            return  # no usable key: leave them unmarked
    system = grade_system(str(attempt["language"]))
    for row in pending:
        source = as_json(row["source"]) or {}
        prompt = grade_prompt(
            row["prompt"],
            row["answer"],
            prepare_untrusted(str(source.get("text") or ""), mask_optional=mask).text,
            prepare_user_text(row["response"], mask_optional=mask).text,
        )
        try:
            reply = await _collect(llm, provider, api_key, model, system, prompt, sleep, backoff)
        except LLMError as exc:
            if exc.code == "invalid_key":
                return
            continue
        graded = parse_grade(reply)
        if graded is None:
            continue
        score, feedback = graded
        async with user_session(factory, owner_id) as session:
            await session.execute(
                text("UPDATE quiz_answers SET score = :s, feedback = :f WHERE id = :i"),
                {"i": row["id"], "s": score, "f": feedback or None},
            )
