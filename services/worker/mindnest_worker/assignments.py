"""AI help on one assignment: a breakdown, an outline, or feedback on the student's draft.

Runs in the background with the student's own AI key. The student's materials are searched for
passages about the assignment; those passages, the brief and the draft all go through the safety
layer before they reach the provider, and the answer is cleaned before it is saved.
"""

import asyncio
import json
import logging
from collections import Counter
from typing import Any
from uuid import UUID

from mindnest_api.llm import LLM, LLMError
from mindnest_api.prompts import build_system_prompt, prepare_passages
from mindnest_api.retrieval import ModelClient, retrieve
from mindnest_core.aisafety import new_canary, prepare_untrusted, prepare_user_text, sanitize_output
from mindnest_core.assignlogic import (
    ATTACHMENT_CHARS,
    TOP_K,
    attachment_block,
    rubric_text,
    search_query,
    task_prompt,
    user_message,
)
from mindnest_core.db import as_json, user_session
from mindnest_core.redact import redact
from mindnest_core.safetystore import OUTPUT_BLOCKED, OUTPUT_CLEANED, record_event, record_prepared
from mindnest_core.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mindnest_worker.llmcalls import RATE_LIMIT_BACKOFF, JobFailed, Sleep, collect, key_for

logger = logging.getLogger("mindnest.assignments")

type SessionFactory = async_sessionmaker[AsyncSession]


async def run_assignment_help(
    run_id: UUID, owner_id: UUID, *, factory: SessionFactory, llm: LLM, models: ModelClient,
    settings: Settings, sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = RATE_LIMIT_BACKOFF,
) -> None:
    """Do one run. Safe to deliver twice: a run that is not waiting is left alone."""
    try:
        await _run(run_id, owner_id, factory, llm, models, settings, sleep, backoff)
    except JobFailed as exc:
        await _fail(factory, owner_id, run_id, exc.code)
    except LLMError as exc:
        await _fail(factory, owner_id, run_id, exc.code)
    except Exception as exc:
        logger.error("Assignment run %s failed: %s", run_id, redact(f"{type(exc).__name__}: {exc}"))
        await _fail(factory, owner_id, run_id, "internal")


async def _attachments(session: AsyncSession, assignment_id: UUID) -> list[tuple[str, str]]:
    """The text of the files attached to the assignment (a question paper, a handout), read in
    order and cut to what one run may use. Files still being read are left out."""
    rows = (
        (
            await session.execute(
                text(
                    "SELECT m.filename, c.text FROM assignment_files f "
                    "JOIN materials m ON m.id = f.material_id AND m.deleted_at IS NULL AND m.status = 'ready' "
                    "JOIN chunks c ON c.material_id = m.id AND c.is_active "
                    "WHERE f.assignment_id = :a "
                    "ORDER BY f.created_at, m.id, c.page NULLS FIRST, c.created_at, c.id"
                ),
                {"a": assignment_id},
            )
        )
        .mappings()
        .all()
    )
    files: dict[str, list[str]] = {}
    used = 0
    for row in rows:
        if used >= ATTACHMENT_CHARS:
            break
        piece = str(row["text"])[: ATTACHMENT_CHARS - used]
        files.setdefault(str(row["filename"]), []).append(piece)
        used += len(piece)
    return [(name, "\n".join(pieces)) for name, pieces in files.items()]


async def _fail(factory: SessionFactory, owner_id: UUID, run_id: UUID, code: str) -> None:
    async with user_session(factory, owner_id) as session:
        await session.execute(
            text(
                "UPDATE assignment_runs SET status = 'failed', error = :e, finished_at = now() "
                "WHERE id = :r AND status IN ('queued', 'running')"
            ),
            {"r": run_id, "e": code},
        )


async def _run(
    run_id: UUID, owner_id: UUID, factory: SessionFactory, llm: LLM, models: ModelClient,
    settings: Settings, sleep: Sleep, backoff: tuple[float, ...],
) -> None:
    async with user_session(factory, owner_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT r.kind, r.language, r.status, r.config, a.title, a.brief, a.draft, "
                        "a.subject_id, a.rubric, r.assignment_id, u.mask_personal_data "
                        "FROM assignment_runs r JOIN assignments a ON a.id = r.assignment_id "
                        "JOIN users u ON u.id = r.user_id WHERE r.id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] not in ("queued", "running"):
            return
        cfg: dict[str, Any] = as_json(row["config"]) or {}
        provider, default_model, api_key = await key_for(session, settings, cfg.get("provider"))
        model = cfg.get("model") or default_model
        mask = bool(row["mask_personal_data"])
        await session.execute(text("UPDATE assignment_runs SET status = 'running' WHERE id = :r"), {"r": run_id})
        kind, language = str(row["kind"]), str(row["language"])
        title, brief, draft = str(row["title"]), str(row["brief"]), str(row["draft"])
        rubric = (as_json(row["rubric"]) or {}).get("criteria") or []
        attachments = await _attachments(session, row["assignment_id"])
        found = await retrieve(
            session, models, search_query(kind, title, brief, draft),
            subject_id=row["subject_id"], candidates=settings.retrieval_candidates, top_k=TOP_K,
        )

    # Everything that goes to the provider is made safe first. The student's own words are
    # masked for personal data but not rewritten; documents are also checked for hidden commands.
    canary = new_canary()
    prepared = prepare_passages(found.passages, mask)
    safe_brief = prepare_user_text(brief, mask_optional=mask)
    safe_draft = prepare_user_text(draft, mask_optional=mask)
    safe_title = prepare_user_text(title, mask_optional=mask)
    safe_rubric = prepare_user_text(rubric_text(rubric), mask_optional=mask)
    # Files the student attached are documents, not their own words: instruction-like text in
    # them is quoted as data, exactly as it is for retrieved passages.
    safe_files = [prepare_untrusted(body, mask_optional=mask) for _, body in attachments]
    file_blocks = [
        attachment_block(name, safe.text) for (name, _), safe in zip(attachments, safe_files, strict=True)
    ]
    system = (
        build_system_prompt(
            found.passages, language, mask_optional=mask, canary=canary, prepared=prepared
        )
        + "\n\n"
        + task_prompt(kind, has_rubric=bool(rubric))
    )
    full_brief = "\n\n".join(part for part in [safe_brief.text.strip(), *file_blocks] if part)
    message = user_message(kind, safe_title.text, full_brief, safe_draft.text, safe_rubric.text)
    reply = await collect(llm, provider, api_key, model, system, message, sleep, backoff)

    safe = sanitize_output(reply, canary=canary)
    pii: Counter[str] = Counter()
    injections = hidden = 0
    for entry in [*prepared, *safe_files, safe_brief, safe_draft, safe_title, safe_rubric]:
        pii.update(entry.pii)
        injections += len(entry.injection)
        hidden += entry.hidden_removed

    sources = [
        {"n": n, "filename": p.filename, "page": p.page, "material_id": str(p.material_id),
         "chunk_id": str(p.chunk_id)}
        for n, p in enumerate(found.passages, start=1)
    ]
    async with user_session(factory, owner_id) as session:
        await record_prepared(session, owner_id, "assignment", pii=pii, injections=injections, hidden=hidden)
        if safe.leaked:
            # Nothing is saved from this answer. The log line is written before failing.
            await record_event(session, owner_id, OUTPUT_BLOCKED, "assignment", {"changes": safe.changes})
        else:
            if safe.changes:
                await record_event(session, owner_id, OUTPUT_CLEANED, "assignment", {"changes": safe.changes})
            await session.execute(
                text(
                    "UPDATE assignment_runs SET status = 'ready', result = :t, error = NULL, "
                    "sources = CAST(:s AS jsonb), finished_at = now() WHERE id = :r"
                ),
                {"r": run_id, "t": safe.text, "s": json.dumps(sources)},
            )
    if safe.leaked:
        raise JobFailed("unsafe_output")
