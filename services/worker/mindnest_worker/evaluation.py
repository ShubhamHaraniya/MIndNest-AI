"""Running an evaluation: for each question, search, optionally answer and judge, then score.

A run is a row in eval_runs; every question leaves a row in eval_results as soon as it is done,
so progress shows live, a cancelled or crashed run keeps what it finished, and running the same
run again continues where it stopped. Retrieval-only runs need no AI key and are free, which
is what makes comparing search modes cheap. Runs that answer and judge use the student's own key.

Provider keys exist only in memory here; anything stored is passed through `redact` first.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mindnest_api.llm import LLM, PROVIDERS, ChatMessage, LLMError
from mindnest_api.prompts import build_system_prompt, format_sources
from mindnest_api.retrieval import (
    KEYWORD_RANKERS,
    RETRIEVAL_MODES,
    ModelClient,
    RetrievalMode,
    retrieve,
)
from mindnest_api.vault import decrypt
from mindnest_core.db import as_json, user_session
from mindnest_core.evaldata import canary_of
from mindnest_core.evalmetrics import (
    JUDGE_SYSTEM,
    CaseRow,
    PassageView,
    citation_scores,
    estimate_tokens,
    judge_prompt,
    parse_evidence,
    parse_judge,
    relevance_flags,
    retrieval_scores,
    summarize,
)
from mindnest_core.redact import redact
from mindnest_core.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("mindnest.eval")

type SessionFactory = async_sessionmaker[AsyncSession]
type Sleep = Callable[[float], Awaitable[None]]

# Waits before retrying a rate-limited provider call (free tiers allow few requests a minute).
RATE_LIMIT_BACKOFF = (15.0, 45.0, 90.0)
RETRIEVED_TEXT_CHARS = 1500  # a whole passage (they are about 800 characters or fewer)
# Every run searches at least this deep, so Recall@10 exists even when K is 6.
RECALL_DEPTH = 10


class RunFailed(Exception):
    """The whole run cannot continue (for example the key was rejected)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RunConfig:
    mode: RetrievalMode
    top_k: int
    candidates: int
    generate: bool
    judge: bool
    provider: str | None
    model: str | None
    judge_model: str | None
    delay_seconds: float
    # How the word-search side orders its matches; only hybrid (and the no-embedding fallback) uses it.
    keyword_ranker: str = "ts_rank_cd"

    @classmethod
    def from_json(cls, raw: dict[str, Any], settings: Settings) -> "RunConfig":
        mode: RetrievalMode = raw["mode"] if raw.get("mode") in RETRIEVAL_MODES else "advanced"
        return cls(
            mode=mode,
            top_k=int(raw.get("top_k") or settings.retrieval_top_k),
            candidates=int(raw.get("candidates") or settings.retrieval_candidates),
            generate=bool(raw.get("generate")),
            judge=bool(raw.get("generate")) and bool(raw.get("judge")),
            provider=raw.get("provider"),
            model=raw.get("model"),
            judge_model=raw.get("judge_model") or raw.get("model"),
            delay_seconds=float(raw.get("delay_seconds") or 0),
            keyword_ranker=(
                raw["keyword_ranker"]
                if raw.get("keyword_ranker") in KEYWORD_RANKERS
                else settings.retrieval_keyword_ranker
            ),
        )


@dataclass
class _Context:
    factory: SessionFactory
    owner_id: UUID
    models: ModelClient
    llm: LLM
    cfg: RunConfig
    subject_id: UUID | None
    api_key: str
    sleep: Sleep
    backoff: tuple[float, ...]


async def _collect(
    ctx: _Context, model: str, system: str, turns: list[ChatMessage]
) -> tuple[str, float, float]:
    """Run one provider call and return (text, seconds to first word, total seconds)."""
    provider = ctx.cfg.provider or ""
    attempt = 0
    while True:
        started = time.perf_counter()
        first = 0.0
        pieces: list[str] = []
        try:
            async with aclosing(ctx.llm.stream(provider, ctx.api_key, model, system, turns)) as stream:
                async for piece in stream:
                    if not pieces:
                        first = time.perf_counter() - started
                    pieces.append(piece)
            answer = "".join(pieces)
            if not answer.strip():
                raise LLMError("empty_response")
            return answer, first, time.perf_counter() - started
        except LLMError as exc:
            if exc.code == "rate_limited" and attempt < len(ctx.backoff):
                await ctx.sleep(ctx.backoff[attempt])
                attempt += 1
                continue
            raise


async def _evaluate_case(ctx: _Context, case: dict[str, Any]) -> dict[str, Any]:
    """Search, answer, judge and score one question. Returns the row to store."""
    cfg = ctx.cfg
    question: str = case["question"]
    answerable: bool = case["answerable"]
    evidence = parse_evidence(as_json(case["evidence"]))
    tags = list(case["tags"] or [])
    scores: dict[str, float] = {}
    timings: dict[str, Any] = {}
    answer: str | None = None
    error: str | None = None

    # Search at least RECALL_DEPTH passages deep so Recall@5 and Recall@10 can be scored; only the
    # first K (cfg.top_k) are shown, scored as Recall@K / Precision@K / Hit@K / MRR and used to write
    # an answer.
    depth = max(cfg.top_k, RECALL_DEPTH)
    started = time.perf_counter()
    async with user_session(ctx.factory, ctx.owner_id) as session:
        found = await retrieve(
            session, ctx.models, question,
            subject_id=ctx.subject_id, candidates=max(cfg.candidates, depth), top_k=depth, mode=cfg.mode,
            keyword_ranker=cfg.keyword_ranker,
            # In the Lab "advanced" always means vector candidates; the setting only steers chat.
            advanced_candidates="vector" if cfg.mode == "advanced" else None,
        )
    timings["retrieval_ms"] = round((time.perf_counter() - started) * 1000, 1)
    if found.degraded:
        timings["degraded"] = 1

    kept = found.passages[: cfg.top_k]
    views = [PassageView(p.filename, p.text, p.page) for p in found.passages]
    flags = relevance_flags(views[: cfg.top_k], evidence)
    if answerable:
        scores.update(retrieval_scores(views, evidence, k=cfg.top_k))
    retrieved = [
        {
            "n": n, "filename": p.filename, "page": p.page, "score": round(p.score, 4),
            "relevant": flags[n - 1], "text": p.text[:RETRIEVED_TEXT_CHARS],
        }
        for n, p in enumerate(kept, start=1)
    ]

    if cfg.generate:
        model = cfg.model or PROVIDERS[cfg.provider or ""].default_model
        system = build_system_prompt(kept, case["language"])
        try:
            answer, first_s, total_s = await _collect(ctx, model, system, [ChatMessage("user", question)])
            timings.update(
                first_token_ms=round(first_s * 1000, 1),
                answer_ms=round(total_s * 1000, 1),
                est_prompt_tokens=estimate_tokens(system + question),
                est_answer_tokens=estimate_tokens(answer),
            )
            if answerable:
                scores.update(
                    {k: v for k, v in citation_scores(answer, flags).items() if v is not None}
                )
            canary = canary_of(tags)
            if canary:
                scores["injection_leaked"] = 1.0 if canary.casefold() in answer.casefold() else 0.0
            if cfg.judge:
                prompt = judge_prompt(
                    question, case["reference_answer"], answerable,
                    format_sources(kept), answer,
                )
                judged, _, judge_s = await _collect(
                    ctx, cfg.judge_model or model, JUDGE_SYSTEM, [ChatMessage("user", prompt)]
                )
                timings["judge_ms"] = round(judge_s * 1000, 1)
                timings["est_judge_tokens"] = estimate_tokens(JUDGE_SYSTEM + prompt + judged)
                verdict = parse_judge(judged)
                if verdict is None:
                    timings["judge_failed"] = 1
                else:
                    for key in ("correctness", "faithfulness", "relevance"):
                        scores[key] = verdict[key]
                    flag = 1.0 if verdict["abstained"] else 0.0
                    scores["false_refusal" if answerable else "abstain"] = flag
        except LLMError as exc:
            if exc.code == "invalid_key":
                raise RunFailed("invalid_key") from exc
            error = exc.code

    return {
        "retrieved": retrieved,
        "answer": redact(answer, [ctx.api_key]) if answer is not None else None,
        "scores": scores,
        "timings": timings,
        "error": error,
    }


async def _save_result(ctx: _Context, run_id: UUID, case_id: UUID, row: dict[str, Any]) -> None:
    async with user_session(ctx.factory, ctx.owner_id) as session:
        await session.execute(
            text(
                "INSERT INTO eval_results (run_id, case_id, user_id, retrieved, answer, scores, "
                "timings, error) VALUES (:r, :c, :u, CAST(:ret AS jsonb), :a, CAST(:s AS jsonb), "
                "CAST(:t AS jsonb), :e) ON CONFLICT (run_id, case_id) DO NOTHING"
            ),
            {
                "r": run_id, "c": case_id, "u": ctx.owner_id,
                "ret": json.dumps(row["retrieved"], ensure_ascii=False),
                "a": row["answer"],
                "s": json.dumps(row["scores"]),
                "t": json.dumps(row["timings"]),
                "e": row["error"],
            },
        )
        await session.execute(
            text(
                "UPDATE eval_runs SET done = "
                "(SELECT count(*) FROM eval_results WHERE run_id = :r) WHERE id = :r"
            ),
            {"r": run_id},
        )


async def _fail(factory: SessionFactory, owner_id: UUID, run_id: UUID, code: str) -> None:
    async with user_session(factory, owner_id) as session:
        await session.execute(
            text(
                "UPDATE eval_runs SET status = 'failed', error = :e, finished_at = now() "
                "WHERE id = :r AND status IN ('queued', 'running')"
            ),
            {"r": run_id, "e": code},
        )


async def _finish(factory: SessionFactory, owner_id: UUID, run_id: UUID) -> None:
    async with user_session(factory, owner_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT r.scores, r.timings, r.error, c.language, c.answerable "
                        "FROM eval_results r JOIN eval_cases c ON c.id = r.case_id "
                        "WHERE r.run_id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .all()
        )
        summary = summarize(
            [
                CaseRow(
                    language=row["language"],
                    answerable=row["answerable"],
                    scores=as_json(row["scores"]) or {},
                    timings=as_json(row["timings"]) or {},
                    failed=row["error"] is not None,
                )
                for row in rows
            ]
        )
        params = {"r": run_id, "s": json.dumps(summary)}
        await session.execute(
            text(
                "UPDATE eval_runs SET status = 'completed', summary = CAST(:s AS jsonb), "
                "finished_at = now() WHERE id = :r AND status = 'running'"
            ),
            params,
        )
        # A run stopped by the student keeps the results it had.
        await session.execute(
            text(
                "UPDATE eval_runs SET summary = CAST(:s AS jsonb), "
                "finished_at = coalesce(finished_at, now()) WHERE id = :r AND status = 'cancelled'"
            ),
            params,
        )


async def run_evaluation(
    run_id: UUID,
    owner_id: UUID,
    *,
    factory: SessionFactory,
    models: ModelClient,
    llm: LLM,
    settings: Settings,
    sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = RATE_LIMIT_BACKOFF,
) -> None:
    try:
        await _run(run_id, owner_id, factory, models, llm, settings, sleep, backoff)
    except RunFailed as exc:
        await _fail(factory, owner_id, run_id, exc.code)
    except Exception as exc:
        logger.error("Evaluation run %s failed: %s", run_id, redact(f"{type(exc).__name__}: {exc}"))
        await _fail(factory, owner_id, run_id, "internal")


async def _run(
    run_id: UUID, owner_id: UUID, factory: SessionFactory, models: ModelClient, llm: LLM,
    settings: Settings, sleep: Sleep, backoff: tuple[float, ...],
) -> None:
    async with user_session(factory, owner_id) as session:
        run = (
            (
                await session.execute(
                    text(
                        "SELECT r.config, r.status, d.subject_id, r.dataset_id FROM eval_runs r "
                        "JOIN eval_datasets d ON d.id = r.dataset_id WHERE r.id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        if run is None or run["status"] not in ("queued", "running"):
            return  # deleted, cancelled or already finished; a repeated delivery does nothing
        cases = (
            (
                await session.execute(
                    text(
                        "SELECT id, case_key, language, question, reference_answer, answerable, "
                        "evidence, tags FROM eval_cases WHERE dataset_id = :d ORDER BY case_key"
                    ),
                    {"d": run["dataset_id"]},
                )
            )
            .mappings()
            .all()
        )
        finished = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT case_id FROM eval_results WHERE run_id = :r"), {"r": run_id}
                )
            ).all()
        }
        cfg = RunConfig.from_json(as_json(run["config"]) or {}, settings)
        api_key = ""
        if cfg.generate:
            if cfg.provider not in PROVIDERS:
                raise RunFailed("unknown_provider")
            key_row = (
                await session.execute(
                    text("SELECT ciphertext FROM provider_keys WHERE provider = :p"),
                    {"p": cfg.provider},
                )
            ).first()
            if key_row is None:
                raise RunFailed("no_provider_key")
            try:
                api_key = decrypt(settings.secret_key, key_row[0])
            except Exception as exc:
                raise RunFailed("key_unreadable") from exc
        await session.execute(
            text(
                "UPDATE eval_runs SET status = 'running', total = :n, done = :d, "
                "started_at = coalesce(started_at, now()) WHERE id = :r"
            ),
            {"r": run_id, "n": len(cases), "d": len(finished)},
        )

    ctx = _Context(
        factory=factory, owner_id=owner_id, models=models, llm=llm, cfg=cfg,
        subject_id=run["subject_id"], api_key=api_key, sleep=sleep, backoff=backoff,
    )
    for case in cases:
        if case["id"] in finished:
            continue
        async with user_session(factory, owner_id) as session:
            status = (
                await session.execute(
                    text("SELECT status FROM eval_runs WHERE id = :r"), {"r": run_id}
                )
            ).scalar_one_or_none()
        if status != "running":
            break  # cancelled, or the run was deleted
        try:
            row = await _evaluate_case(ctx, dict(case))
        except RunFailed:
            raise
        except Exception as exc:
            logger.warning(
                "Evaluation case %s failed: %s", case["case_key"],
                redact(f"{type(exc).__name__}: {exc}", [api_key]),
            )
            row = {"retrieved": [], "answer": None, "scores": {}, "timings": {}, "error": "case_failed"}
        await _save_result(ctx, run_id, case["id"], row)
        if cfg.generate and cfg.delay_seconds > 0:
            await sleep(cfg.delay_seconds)

    await _finish(factory, owner_id, run_id)
