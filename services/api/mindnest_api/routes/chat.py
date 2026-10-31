"""Chat: conversations and streamed, cited answers grounded in the student's materials."""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from mindnest_agents import GRAPH_VERSION, runs
from mindnest_agents.checkpoint import thread_id
from mindnest_agents.errors import AgentError
from mindnest_agents.guardrails import Guardrails
from mindnest_agents.tracing import make_tracing
from mindnest_core.aisafety import SafeOutput, canary_for, prepare_user_text, sanitize_output
from mindnest_core.calevent import EventEdits
from mindnest_core.chatlogic import (
    ChatRuleError,
    Choices,
    RegeneratePlan,
    attachment_context,
    excerpt,
    like_pattern,
    plan_regenerate,
    sanitize_diagram_blocks,
    scope_from_row,
    search_filter,
    split_tail,
    normalize_citation_marks,
    strip_unknown_citations,
)
from mindnest_core.safetystore import (
    GUARD_BLOCKED,
    GUARD_CLEANED,
    GUARD_REVIEWED,
    OUTPUT_BLOCKED,
    OUTPUT_CLEANED,
    record_event,
    record_prepared,
)
from mindnest_core.settings import get_settings
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from mindnest_api.agent.context import AgentContext, SubjectInfo
from mindnest_api.agent.runner import Turn, stream_run
from mindnest_api.deps import (
    AuthUser,
    CalendarGatewayDep,
    GuardrailsDep,
    ChatModelsDep,
    LimiterDep,
    ModelsDep,
    QueueDep,
    StorageDep,
    UserDb,
    UserDbDep,
)
from mindnest_api.errors import AppError
from mindnest_api.llm import PROVIDERS, ChatMessage, ProviderId
from mindnest_api.prompts import normalize_history, title_from
from mindnest_api.vault import decrypt

router = APIRouter(tags=["chat"])
logger = logging.getLogger("mindnest.chat")

MODEL_NAME = re.compile(r"^[\w.:/\-]{1,100}$")
DEFAULT_TITLE = "New chat"

# A proposal the student has not answered for this long is treated as expired.
APPROVAL_TTL_HOURS = 24

Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class ConversationOut(BaseModel):
    id: UUID
    subject_id: UUID | None
    title: str
    provider: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime
    # What the conversation may search: "all" courses, one "subject", or chosen "materials".
    scope: str = "all"
    material_ids: list[UUID] = Field(default_factory=list)
    # When the list was searched: a short piece of the chat that matched (None: the title matched).
    match: str | None = None


class MessageOut(BaseModel):
    id: UUID
    role: str
    blocks: list[dict[str, Any]]
    created_at: datetime
    # The student's own thumbs up/down on this answer, and the answer it replaced (if any).
    feedback: dict[str, Any] | None = None
    replaces_id: UUID | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationIn(BaseModel):
    subject_id: UUID | None = None


class ConversationPatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SendIn(BaseModel):
    content: Content
    provider: ProviderId | None = None
    model: str | None = None
    # Write this answer again (it must be the newest one). `content` is then ignored: the student's
    # earlier question is used.
    regenerate_of: UUID | None = None


_CONVERSATION_COLUMNS = "id, subject_id, title, provider, model, created_at, updated_at, scope, material_ids"


async def _get_conversation(session: Any, conversation_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "not_found", "Conversation not found.")
    return dict(row)


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    _user: AuthUser,
    db: UserDbDep,
    subject_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[ConversationOut]:
    """The student's chats, newest first. With `q`, only chats whose title or messages contain it
    (plain text, case does not matter), each with a short piece of the text that matched."""
    term = (q or "").strip()
    pattern = like_pattern(term) if len(term) >= 2 else None
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT {_CONVERSATION_COLUMNS} FROM conversations c "
                        "WHERE (CAST(:s AS uuid) IS NULL OR c.subject_id = CAST(:s AS uuid)) "
                        "AND (CAST(:p AS text) IS NULL OR c.title ILIKE CAST(:p AS text) ESCAPE '\\' "
                        "OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id "
                        "AND m.superseded_at IS NULL AND CAST(m.blocks AS text) ILIKE CAST(:p AS text) ESCAPE '\\')) "
                        "ORDER BY c.updated_at DESC LIMIT 100"
                    ),
                    {"s": str(subject_id) if subject_id else None, "p": pattern},
                )
            )
            .mappings()
            .all()
        )
        matches: dict[UUID, str] = {}
        if pattern is not None and rows:
            found = (
                (
                    await session.execute(
                        text(
                            "SELECT DISTINCT ON (m.conversation_id) m.conversation_id, m.blocks "
                            "FROM messages m WHERE m.conversation_id = ANY(CAST(:ids AS uuid[])) "
                            "AND m.superseded_at IS NULL AND CAST(m.blocks AS text) ILIKE CAST(:p AS text) ESCAPE '\\' "
                            "ORDER BY m.conversation_id, m.created_at DESC"
                        ),
                        {"ids": [str(r["id"]) for r in rows], "p": pattern},
                    )
                )
                .mappings()
                .all()
            )
            for hit in found:
                piece = excerpt(_text_of(_as_blocks(hit["blocks"])), term)
                if piece:
                    matches[hit["conversation_id"]] = piece
    return [ConversationOut(**row, match=matches.get(row["id"])) for row in rows]


@router.post("/conversations", status_code=201, response_model=ConversationOut)
async def create_conversation(body: ConversationIn, user: AuthUser, db: UserDbDep) -> ConversationOut:
    async with db.session() as session:
        if body.subject_id is not None:
            visible = (
                await session.execute(
                    text("SELECT 1 FROM subjects WHERE id = :id AND archived_at IS NULL"),
                    {"id": body.subject_id},
                )
            ).scalar_one_or_none()
            if visible is None:
                raise AppError(404, "not_found", "Subject not found.")
        row = (
            (
                await session.execute(
                    text(
                        "INSERT INTO conversations (user_id, subject_id, title, scope) "
                        f"VALUES (:u, :s, :t, :k) RETURNING {_CONVERSATION_COLUMNS}"
                    ),
                    {
                        "u": user.id, "s": body.subject_id, "t": DEFAULT_TITLE,
                        "k": "subject" if body.subject_id is not None else "all",
                    },
                )
            )
            .mappings()
            .one()
        )
    return ConversationOut(**row)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID, user: AuthUser, db: UserDbDep
) -> ConversationDetail:
    async with db.session() as session:
        conversation = await _get_conversation(session, conversation_id)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT m.id, m.role, m.blocks, m.created_at, m.replaces_id, "
                        "f.rating AS fb_rating, f.reason AS fb_reason FROM messages m "
                        "LEFT JOIN message_feedback f ON f.message_id = m.id AND f.user_id = :u "
                        "WHERE m.conversation_id = :c AND m.superseded_at IS NULL "
                        "ORDER BY m.created_at, m.id LIMIT 500"
                    ),
                    {"c": conversation_id, "u": user.id},
                )
            )
            .mappings()
            .all()
        )
        waiting = {
            str(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT id FROM agent_runs WHERE conversation_id = :c AND status = 'interrupted' "
                        "AND updated_at > now() - make_interval(hours => :h)"
                    ),
                    {"c": conversation_id, "h": APPROVAL_TTL_HOURS},
                )
            ).scalars()
        }
    messages = [
        MessageOut(
            id=row["id"],
            role=row["role"],
            blocks=_expire_proposals(_as_blocks(row["blocks"]), waiting),
            created_at=row["created_at"],
            feedback=(
                {"rating": row["fb_rating"], "reason": row["fb_reason"]}
                if row["fb_rating"] is not None else None
            ),
            replaces_id=row["replaces_id"],
        )
        for row in rows
    ]
    return ConversationDetail(**conversation, messages=messages)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: UUID, body: ConversationPatch, _user: AuthUser, db: UserDbDep
) -> ConversationOut:
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE conversations SET title = :t WHERE id = :id "
                        f"RETURNING {_CONVERSATION_COLUMNS}"
                    ),
                    {"t": body.title, "id": conversation_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise AppError(404, "not_found", "Conversation not found.")
    return ConversationOut(**row)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID, _user: AuthUser, db: UserDbDep, storage: StorageDep
) -> Response:
    async with db.session() as session:
        keys = list(
            (
                await session.execute(
                    text("SELECT storage_key FROM chat_attachments WHERE conversation_id = :id"),
                    {"id": conversation_id},
                )
            ).scalars()
        )
        result = await session.execute(
            text("DELETE FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(404, "not_found", "Conversation not found.")
    for key in keys:  # the rows went with the conversation; the stored files go too
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            logger.warning("Could not delete a stored chat file", exc_info=True)
    return Response(status_code=204)


def _sse(event: str, data: dict[str, Any]) -> str:
    # json.dumps escapes newlines, so the payload always fits on one `data:` line.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _as_blocks(value: Any) -> list[dict[str, Any]]:
    """jsonb arrives as a JSON string or as a list, depending on the driver's codec."""
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


def _expire_proposals(blocks: list[dict[str, Any]], waiting: set[str]) -> list[dict[str, Any]]:
    """A proposal card still marked "pending" whose run is no longer waiting for the student (a
    newer message was sent, or too much time passed) is shown as expired, so it cannot be pressed."""
    for block in blocks:
        data = block.get("data")
        if (
            block.get("type") == "card" and block.get("kind") == "calendar_proposal"
            and isinstance(data, dict) and data.get("status") == "pending"
            and str(data.get("run_id")) not in waiting
        ):
            block["data"] = {**data, "status": "expired"}
    return blocks


def _text_of(blocks: list[dict[str, Any]]) -> str:
    return "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    body: SendIn,
    user: AuthUser,
    db: UserDbDep,
    chat_models: ChatModelsDep,
    models: ModelsDep,
    queue: QueueDep,
    limiter: LimiterDep,
    calendar: CalendarGatewayDep,
    guard: GuardrailsDep,
) -> StreamingResponse:
    settings = get_settings()
    await limiter.check(f"chat:{user.id}", settings.chat_rate_per_minute, 60)
    if body.model is not None and not MODEL_NAME.match(body.model):
        raise AppError(422, "validation_error", "That model name is not valid.")

    mask = user.mask_personal_data
    # Everything that can fail with a normal error happens before streaming starts.
    async with db.session() as session:
        conversation = await _get_conversation(session, conversation_id)
        provider = body.provider or conversation["provider"]
        key_row = (
            (
                await session.execute(
                    text(
                        "SELECT provider, ciphertext, model FROM provider_keys "
                        "WHERE (CAST(:p AS text) IS NULL OR provider = :p) "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"p": provider},
                )
            )
            .mappings()
            .first()
        )
        if key_row is None:
            raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")

        # Writing an answer again: only the newest answer, and it needs the question before it.
        regenerate: RegeneratePlan | None = None
        question_text = body.content
        if body.regenerate_of is not None:
            turns = [
                (str(r["id"]), str(r["role"]))
                for r in (
                    await session.execute(
                        text(
                            "SELECT id, role FROM messages WHERE conversation_id = :c "
                            "AND superseded_at IS NULL AND role IN ('user', 'assistant') "
                            "ORDER BY created_at, id"
                        ),
                        {"c": conversation_id},
                    )
                ).mappings()
            ]
            try:
                regenerate = plan_regenerate(turns, str(body.regenerate_of))
            except ChatRuleError as exc:
                raise AppError(409, exc.code, "Only the newest answer can be written again.") from exc
            asked_blocks = (
                await session.execute(
                    text("SELECT blocks FROM messages WHERE id = :m"), {"m": regenerate.user_message_id}
                )
            ).scalar_one()
            question_text = _text_of(_as_blocks(asked_blocks)) or body.content
        skip = (
            [regenerate.user_message_id, regenerate.assistant_message_id] if regenerate else None
        )
        previous = (
            (
                await session.execute(
                    text(
                        "SELECT role, blocks FROM messages WHERE conversation_id = :c "
                        "AND superseded_at IS NULL "
                        "AND (CAST(:skip AS uuid[]) IS NULL OR id <> ALL(CAST(:skip AS uuid[]))) "
                        "ORDER BY created_at DESC, id DESC LIMIT :n"
                    ),
                    {"c": conversation_id, "n": settings.chat_history_messages, "skip": skip},
                )
            )
            .mappings()
            .all()
        )
        attached = [
            (str(r["filename"]), str(r["text_content"]))
            for r in (
                await session.execute(
                    text(
                        "SELECT filename, text_content FROM chat_attachments "
                        "WHERE conversation_id = :c AND status = 'ready' ORDER BY created_at, id"
                    ),
                    {"c": conversation_id},
                )
            ).mappings()
        ]
        history = normalize_history(
            [
                ChatMessage(row["role"], _text_of(_as_blocks(row["blocks"])))
                for row in reversed(previous)
                if row["role"] in ("user", "assistant")
            ]
        )
        subjects = await _subject_overview(session)

        used_provider = str(key_row["provider"])
        # A model chosen earlier in this conversation sticks, as long as the provider is the same.
        earlier = conversation["model"] if conversation["provider"] == used_provider else None
        used_model = (
            body.model or earlier or key_row["model"] or PROVIDERS[used_provider].default_model
        )
        if regenerate is not None:
            user_message_id = UUID(regenerate.user_message_id)
        else:
            user_message_id = (
                await session.execute(
                    text(
                        "INSERT INTO messages (conversation_id, role, blocks) "
                        "VALUES (:c, 'user', CAST(:b AS jsonb)) RETURNING id"
                    ),
                    {
                        "c": conversation_id,
                        "b": json.dumps([{"type": "text", "text": body.content}], ensure_ascii=False),
                    },
                )
            ).scalar_one()
        title = conversation["title"]
        if title == DEFAULT_TITLE:
            title = title_from(question_text)
        await session.execute(
            text(
                "UPDATE conversations SET title = :t, provider = :p, model = :m, updated_at = now() "
                "WHERE id = :id"
            ),
            {"t": title, "p": used_provider, "m": used_model, "id": conversation_id},
        )
        thread = thread_id(user.id, conversation_id)
        # A new message means the student moved on: proposals still waiting for an answer lapse.
        await session.execute(
            text(
                "UPDATE agent_runs SET status = 'cancelled', interrupt = NULL, updated_at = now() "
                "WHERE conversation_id = :c AND status = 'interrupted'"
            ),
            {"c": conversation_id},
        )
        run_id = await runs.start_run(
            session, user_id=user.id, conversation_id=conversation_id,
            graph_version=GRAPH_VERSION, thread_id=thread,
        )

    api_key = decrypt(settings.secret_key, key_row["ciphertext"])
    canary = canary_for(settings.secret_key, run_id)
    scope = scope_from_row(conversation["scope"], conversation["subject_id"], conversation["material_ids"])
    where = search_filter(scope)
    tracing = make_tracing(
        settings, run_id=run_id, user_id=user.id, graph_version=GRAPH_VERSION
    )

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "meta",
            {
                "conversation_id": str(conversation_id),
                "user_message_id": str(user_message_id),
                "run_id": str(run_id),
                "title": title,
                "provider": used_provider,
                "model": used_model,
            },
        )
        started = time.perf_counter()
        turn = Turn()
        error: str | None = None
        finished = False
        message_id: UUID | None = None
        safe = SafeOutput("")
        fin: Finalized | None = None
        ctx: AgentContext | None = None
        try:
            # Everything that goes to the provider is first made safe: hidden characters removed,
            # personal data masked. The student's own stored messages are not changed.
            asked = prepare_user_text(question_text, mask_optional=mask)
            safe_history = [
                ChatMessage(m.role, prepare_user_text(m.content, mask_optional=mask).text)
                for m in history
            ]
            llm = chat_models(
                used_provider, used_model, api_key,
                max_tokens=settings.agent_max_output_tokens, timeout=settings.llm_timeout_seconds,
            )
            ctx = AgentContext(
                settings=settings, user=user, db=db, models=models, queue=queue, limiter=limiter, llm=llm,
                provider=used_provider, model=used_model, conversation_id=conversation_id,
                run_id=run_id, canary=canary, question=asked.text, history=safe_history,
                subject_id=where.subject_id, subjects=subjects, calendar=calendar, guard=guard,
                scope_kind=scope.kind, material_ids=where.material_ids, search_nothing=where.nothing,
            )
            if attached:
                block, _cut = attachment_context(attached)
                ctx.attachment_text = ctx.untrusted(block)
            ctx.pii.update(asked.pii)
            ctx.hidden += asked.hidden_removed
            async for event in stream_run(ctx, turn, tracing, thread):
                yield _sse(event["type"], {k: v for k, v in event.items() if k != "type"})
            if not turn.answer.strip() and not turn.cards:
                raise AgentError("empty_response")
            finished = True
        except AgentError as exc:
            error = exc.code
        except Exception:
            logger.exception("Chat turn failed")
            error = "internal"
        finally:
            # Runs even when the browser disconnects (Stop button), so a partial answer is kept.
            elapsed = time.perf_counter() - started
            logger.info(
                "chat turn: total %.2fs (%s, %s, %d sources, route %s)",
                elapsed, used_provider, used_model, len(turn.sources),
                ",".join((turn.route or {}).get("agents", [])) or "-",
            )
            raw_answer = turn.answer
            with anyio.CancelScope(shield=True):
                safe = await _guarded_output(guard, raw_answer, canary, ctx)
            if safe.leaked:
                error = "unsafe_output"
            # Pictures are checked, citation marks that name no retrieved passage are removed, and
            # the machine-readable follow-up / choice blocks are taken off the end of the answer.
            fin = finalize_answer(safe.text, question_text, turn.sources)
            answer = fin.text
            with anyio.CancelScope(shield=True):
                if safe.changed:
                    await _log_output(db, user.id, safe)
                if ctx is not None and (ctx.pii or ctx.injections or ctx.hidden):
                    await _log_prepared(db, user.id, ctx)
                if ctx is not None and ctx.guard_log:
                    await _log_guard(db, user.id, ctx)
                # An answer written again only replaces the old one when it finished cleanly;
                # otherwise the old answer stays and nothing new is saved.
                keep_old = regenerate is not None and (error is not None or not finished)
                if (answer.strip() or turn.cards) and not keep_old:
                    message_id = await _save_answer(
                        db, conversation_id, answer, turn, error, finished, run_id,
                        fin=fin if finished and not error else None,
                        replaces=UUID(regenerate.assistant_message_id) if regenerate else None,
                    )
                await _finish_run(db, run_id, ctx, error, finished, elapsed, turn.interrupt)

        if safe.changes and not safe.leaked:
            # The words already shown are replaced by the cleaned version that was saved.
            yield _sse("safety", {"text": safe.text, "changes": safe.changes})
        if fin is not None and not safe.leaked and (
            fin.text.strip() != safe.text.strip() or fin.followups or fin.choices is not None
        ):
            # The same, for the picture / citation checks and the blocks taken off the end.
            yield _sse("final", fin.event(show_suggestions=finished and not error))
        if error:
            yield _sse("error", {"code": error, "message_id": str(message_id) if message_id else None})
        else:
            yield _sse("done", {
                "message_id": str(message_id), "awaiting_approval": turn.interrupt is not None,
                "usage": _usage(ctx),
                "replaces": regenerate.assistant_message_id if regenerate else None,
            })

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@dataclass
class Finalized:
    """An answer after the last checks: the text to save and show, and what was taken off its end."""

    text: str
    followups: list[str] = field(default_factory=list)
    choices: Choices | None = None
    diagrams_refused: int = 0
    citations_removed: list[int] = field(default_factory=list)

    def event(self, *, show_suggestions: bool) -> dict[str, Any]:
        return {
            "text": self.text,
            "followups": self.followups if show_suggestions else [],
            "choices": (
                {"question": self.choices.question, "options": list(self.choices.options)}
                if self.choices is not None and show_suggestions else None
            ),
            "diagrams_refused": self.diagrams_refused,
            "citations_removed": self.citations_removed,
        }


def finalize_answer(answer: str, asked: str, sources: list[dict[str, Any]] | None) -> Finalized:
    """Check the pictures, drop citation marks that name no retrieved passage (`sources` None: leave
    them, for text that continues an earlier answer), and split off the follow-up / choice blocks."""
    cleaned, refused = sanitize_diagram_blocks(normalize_citation_marks(answer))
    removed: list[int] = []
    if sources is not None:
        cleaned, removed = strip_unknown_citations(cleaned, [int(s["n"]) for s in sources])
    tail = split_tail(cleaned, asked=asked)
    return Finalized(tail.text, tail.followups, tail.choices, refused, removed)


async def _subject_overview(session: Any) -> list[SubjectInfo]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT s.id, s.name, (SELECT count(*) FROM materials m WHERE m.subject_id = s.id "
                    "AND m.deleted_at IS NULL AND m.status = 'ready') AS ready "
                    "FROM subjects s WHERE s.archived_at IS NULL ORDER BY s.name LIMIT 50"
                )
            )
        )
        .mappings()
        .all()
    )
    return [SubjectInfo(r["id"], r["name"], int(r["ready"])) for r in rows]


async def _log_output(db: UserDb, user_id: UUID, safe: SafeOutput) -> None:
    try:
        async with db.session() as session:
            kind = OUTPUT_BLOCKED if safe.leaked else OUTPUT_CLEANED
            await record_event(session, user_id, kind, "chat", {"changes": safe.changes})
    except Exception:
        logger.warning("Could not log a cleaned answer")


def _usage(ctx: AgentContext | None) -> dict[str, int]:
    """Tokens the run used (the student's own key pays for them), for the screen and for evaluation."""
    if ctx is None:
        return {"prompt_tokens": 0, "completion_tokens": 0}
    return {"prompt_tokens": ctx.prompt_tokens, "completion_tokens": ctx.completion_tokens}


async def _guarded_output(
    guard: Guardrails | None, raw: str, canary: str, ctx: AgentContext | None
) -> SafeOutput:
    """The output rail on the finished answer. The result has the same shape as sanitize_output's,
    which is what runs inside the rail (a leaked marker blocks, links and HTML are cleaned)."""
    if not raw.strip():
        return SafeOutput("")
    if guard is None:
        return sanitize_output(raw, canary=canary)
    decision = await guard.check_output(raw, canary=canary)
    if ctx is not None:
        await ctx.note_guard(decision)
    if decision.blocked:
        return SafeOutput("", ["canary"], leaked=True)
    if decision.action == "modify" and decision.text is not None:
        return SafeOutput(decision.text, list(decision.reasons))
    return SafeOutput(raw)


async def _log_guard(db: UserDb, user_id: UUID, ctx: AgentContext) -> None:
    """One safety-log line per rail that stopped, cleaned or second-guessed something. Labels and
    timings only; the student's words are never written."""
    try:
        async with db.session() as session:
            for detail in ctx.guard_log:
                kind = (
                    GUARD_BLOCKED if detail.get("action") == "block"
                    else GUARD_CLEANED if detail.get("action") == "modify"
                    else GUARD_REVIEWED
                )
                await record_event(session, user_id, kind, "chat", detail)
    except Exception:
        logger.warning("Could not log the guardrail decisions")


async def _log_prepared(db: UserDb, user_id: UUID, ctx: AgentContext) -> None:
    try:
        async with db.session() as session:
            await record_prepared(
                session, user_id, "chat", pii=ctx.pii, injections=ctx.injections, hidden=ctx.hidden
            )
    except Exception:
        logger.warning("Could not log the safety counts")


async def _finish_run(
    db: UserDb, run_id: UUID, ctx: AgentContext | None, error: str | None, finished: bool, elapsed: float,
    waiting: dict[str, Any] | None = None,
) -> None:
    status = "completed" if finished else ("failed" if error else "cancelled")
    if waiting is not None and finished:
        status = "interrupted"  # paused for the student's approval; the checkpoint holds the rest
    try:
        async with db.session() as session:
            await runs.finish_run(
                session, run_id, status=status,
                prompt_tokens=ctx.prompt_tokens if ctx else None,
                completion_tokens=ctx.completion_tokens if ctx else None,
                latency_ms=int(elapsed * 1000), error=error,
                interrupt=waiting if status == "interrupted" else None,
            )
    except Exception:
        logger.warning("Could not close the agent run record")


async def _save_answer(
    db: UserDb,
    conversation_id: UUID,
    answer: str,
    turn: Turn,
    error: str | None,
    finished: bool,
    run_id: UUID,
    fin: Finalized | None = None,
    replaces: UUID | None = None,
) -> UUID | None:
    blocks: list[dict[str, Any]] = []
    if answer.strip():
        blocks.append({"type": "text", "text": answer})
    if fin is not None and fin.followups:
        blocks.append({"type": "followups", "items": fin.followups})
    if fin is not None and fin.choices is not None:
        blocks.append({
            "type": "choices", "question": fin.choices.question, "options": list(fin.choices.options),
        })
    if turn.sources:
        blocks.append({"type": "sources", "items": turn.sources})
    steps = turn.step_list()
    if steps:
        blocks.append({"type": "steps", "items": steps, "route": turn.route})
    for card in turn.cards:
        blocks.append({"type": "card", **card})
    if error:
        blocks.append({"type": "error", "code": error})
    elif not finished:
        blocks.append({"type": "stopped"})
    try:
        async with db.session() as session:
            new_id = (
                await session.execute(
                    text(
                        "INSERT INTO messages (conversation_id, role, blocks, run_id, replaces_id) "
                        "VALUES (:c, 'assistant', CAST(:b AS jsonb), :r, :rep) RETURNING id"
                    ),
                    {
                        "c": conversation_id, "b": json.dumps(blocks, ensure_ascii=False), "r": run_id,
                        "rep": replaces,
                    },
                )
            ).scalar_one()
            if replaces is not None:
                await session.execute(
                    text("UPDATE messages SET superseded_at = now() WHERE id = :m AND superseded_at IS NULL"),
                    {"m": replaces},
                )
            await session.execute(
                text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
                {"id": conversation_id},
            )
        return new_id  # type: ignore[no-any-return]
    except Exception:
        logger.exception("Could not save the assistant message")
        return None


# ------------------------------------------------------------------------------ approvals


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    edits: EventEdits | None = None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _merge_blocks(blocks: list[dict[str, Any]], answer: str, turn: Turn, error: str | None, finished: bool) -> list[dict[str, Any]]:
    """The saved assistant message with what happened after the student decided: the rest of the
    answer, the finished steps, the settled proposal card and any new cards."""
    merged = [dict(b) for b in blocks if b.get("type") not in ("error", "stopped")]
    if answer.strip():
        existing = next((b for b in merged if b.get("type") == "text"), None)
        if existing is None:
            merged.insert(0, {"type": "text", "text": answer})
        else:
            before = str(existing.get("text", ""))
            existing["text"] = f"{before}\n\n{answer}" if before.strip() else answer
    if turn.sources and not any(b.get("type") == "sources" for b in merged):
        merged.append({"type": "sources", "items": turn.sources})
    if turn.steps:
        block = next((b for b in merged if b.get("type") == "steps"), None)
        if block is None:
            merged.append({"type": "steps", "items": turn.step_list(), "route": turn.route})
        else:
            by_id = {int(i["id"]): i for i in block.get("items", []) if isinstance(i, dict) and "id" in i}
            by_id.update(turn.steps)
            block["items"] = [by_id[k] for k in sorted(by_id)]
    for update in turn.card_updates:
        for block in merged:
            data = block.get("data")
            if (
                block.get("type") == "card" and isinstance(data, dict)
                and data.get("proposal_id") == update.get("proposal_id")
            ):
                block["data"] = {**data, **{k: v for k, v in update.items() if k != "proposal_id"}}
    merged.extend({"type": "card", **card} for card in turn.cards)
    if error:
        merged.append({"type": "error", "code": error})
    elif not finished:
        merged.append({"type": "stopped"})
    return merged


@router.post("/conversations/{conversation_id}/runs/{run_id}/decision")
async def decide(
    conversation_id: UUID,
    run_id: UUID,
    body: DecisionIn,
    user: AuthUser,
    db: UserDbDep,
    chat_models: ChatModelsDep,
    models: ModelsDep,
    queue: QueueDep,
    limiter: LimiterDep,
    calendar: CalendarGatewayDep,
    guard: GuardrailsDep,
) -> StreamingResponse:
    """The student's answer to a proposal the chat paused on (approve, edit-and-approve, cancel).

    The run continues from where it paused and its answer is added to the message that holds the
    proposal card. Only the newest run of the conversation can be answered, once, and only while
    it is still fresh; anything else is 409 `approval_expired`."""
    settings = get_settings()
    await limiter.check(f"chat:{user.id}", settings.chat_rate_per_minute, 60)
    expired = AppError(409, "approval_expired", "This request has expired. Ask again in a new message.")
    async with db.session() as session:
        conversation = await _get_conversation(session, conversation_id)
        run = (
            (
                await session.execute(
                    text(
                        "SELECT status, interrupt, thread_id, "
                        "(updated_at > now() - make_interval(hours => :h)) AS fresh "
                        "FROM agent_runs WHERE id = :r AND conversation_id = :c"
                    ),
                    {"r": run_id, "c": conversation_id, "h": APPROVAL_TTL_HOURS},
                )
            )
            .mappings()
            .first()
        )
        if run is None:
            raise AppError(404, "not_found", "That request was not found.")
        latest = (
            await session.execute(
                text(
                    "SELECT id FROM agent_runs WHERE conversation_id = :c "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"c": conversation_id},
            )
        ).scalar_one()
        if run["status"] != "interrupted" or not run["fresh"] or latest != run_id:
            raise expired
        key_row = (
            (
                await session.execute(
                    text("SELECT provider, ciphertext, model FROM provider_keys WHERE provider = :p"),
                    {"p": conversation["provider"]},
                )
            )
            .mappings()
            .first()
        )
        if key_row is None:
            raise AppError(409, "no_provider_key", "Add an AI provider key in Settings first.")
        saved = (
            (
                await session.execute(
                    text("SELECT id, blocks FROM messages WHERE run_id = :r AND role = 'assistant' LIMIT 1"),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        if saved is None:
            raise expired
        subjects = await _subject_overview(session)
        scope = scope_from_row(conversation["scope"], conversation["subject_id"], conversation["material_ids"])
        where = search_filter(scope)
        # Last, so that every check above has passed before the run is taken out of the waiting state.
        if not await runs.resume_run(session, run_id):
            raise expired

    used_provider = str(key_row["provider"])
    used_model = conversation["model"] or key_row["model"] or PROVIDERS[used_provider].default_model
    cursor = _object(_object(run["interrupt"]).get("cursor"))
    thread = str(run["thread_id"] or thread_id(user.id, conversation_id))
    api_key = decrypt(settings.secret_key, key_row["ciphertext"])
    message_id: UUID = saved["id"]
    saved_blocks = _as_blocks(saved["blocks"])
    resume_value: dict[str, Any] = {
        "approved": body.decision == "approve",
        "edits": body.edits.model_dump(exclude_unset=True, mode="json") if body.edits else {},
    }
    # The run keeps its id (and so its canary); only the tracing run is new, because LangSmith
    # does not take a second root run with the same id.
    tracing = make_tracing(settings, run_id=uuid4(), user_id=user.id, graph_version=GRAPH_VERSION)

    async def events() -> AsyncIterator[str]:
        yield _sse("meta", {"conversation_id": str(conversation_id), "run_id": str(run_id),
                            "message_id": str(message_id), "decision": body.decision})
        started = time.perf_counter()
        turn = Turn()
        error: str | None = None
        finished = False
        safe = SafeOutput("")
        ctx: AgentContext | None = None
        canary = canary_for(settings.secret_key, run_id)
        try:
            llm = chat_models(
                used_provider, used_model, api_key,
                max_tokens=settings.agent_max_output_tokens, timeout=settings.llm_timeout_seconds,
            )
            ctx = AgentContext(
                settings=settings, user=user, db=db, models=models, queue=queue, limiter=limiter, llm=llm,
                provider=used_provider, model=used_model, conversation_id=conversation_id,
                run_id=run_id, canary=canary, question="", history=[],
                subject_id=where.subject_id, subjects=subjects, calendar=calendar, guard=guard,
                scope_kind=scope.kind, material_ids=where.material_ids, search_nothing=where.nothing,
            )
            ctx.resume_at(int(cursor.get("step", 0)), int(cursor.get("turn", 0)))
            async for event in stream_run(ctx, turn, tracing, thread, resume=resume_value):
                yield _sse(event["type"], {k: v for k, v in event.items() if k != "type"})
            finished = True
        except AgentError as exc:
            error = exc.code
        except Exception:
            logger.exception("Chat decision failed")
            error = "internal"
        finally:
            elapsed = time.perf_counter() - started
            raw_answer = turn.answer
            with anyio.CancelScope(shield=True):
                safe = await _guarded_output(guard, raw_answer, canary, ctx)
            if safe.leaked:
                error = "unsafe_output"
            with anyio.CancelScope(shield=True):
                if safe.changed:
                    await _log_output(db, user.id, safe)
                if ctx is not None and (ctx.pii or ctx.injections or ctx.hidden):
                    await _log_prepared(db, user.id, ctx)
                if ctx is not None and ctx.guard_log:
                    await _log_guard(db, user.id, ctx)
                try:
                    async with db.session() as session:
                        await session.execute(
                            text("UPDATE messages SET blocks = CAST(:b AS jsonb) WHERE id = :id"),
                            {"b": json.dumps(_merge_blocks(saved_blocks, finalize_answer(safe.text, "", None).text, turn, error, finished),
                                             ensure_ascii=False), "id": message_id},
                        )
                except Exception:
                    logger.exception("Could not save the continued assistant message")
                await _finish_run(db, run_id, ctx, error, finished, elapsed, turn.interrupt)

        if safe.changes and not safe.leaked:
            yield _sse("safety", {"text": safe.text, "changes": safe.changes})
        if error:
            yield _sse("error", {"code": error, "message_id": str(message_id)})
        else:
            yield _sse("done", {"message_id": str(message_id), "awaiting_approval": turn.interrupt is not None, "usage": _usage(ctx)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
