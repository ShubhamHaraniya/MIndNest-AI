"""Everything one agent run needs, gathered once and shared by the graph's nodes and tools.

An AgentContext lives for one student message. It holds the student's identity, a database
handle that applies row-level security, the chat model built with the student's own key, and the
counters the route reports at the end. It is never stored in graph state or checkpoints, and the
provider key itself is not kept here at all: only the already-built model is.
"""

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.config import get_stream_writer
from mindnest_agents import runs
from mindnest_agents.guardrails import Decision, Guardrails
from mindnest_core.aisafety import Prepared, prepare_untrusted
from mindnest_core.settings import Settings
from sqlalchemy import text

from mindnest_api.calendar_gateway import CalendarGateway
from mindnest_api.deps import CurrentUser, UserDb
from mindnest_api.jobs import IngestQueue
from mindnest_api.llm import ChatMessage
from mindnest_api.ratelimit import Limiter
from mindnest_api.prompts import format_numbered_sources
from mindnest_api.retrieval import ModelClient, Passage, retrieve

logger = logging.getLogger("mindnest.agent")

SNIPPET_CHARS = 500


@dataclass
class SubjectInfo:
    id: UUID
    name: str
    ready_materials: int = 0


@dataclass
class SearchResult:
    text: str  # <source> blocks to show the model (empty string when nothing was found)
    new_sources: int
    found: int
    degraded: bool


@dataclass
class AgentContext:
    settings: Settings
    user: CurrentUser
    db: UserDb
    models: ModelClient
    queue: IngestQueue
    limiter: Limiter
    llm: BaseChatModel
    provider: str
    model: str
    conversation_id: UUID
    run_id: UUID
    canary: str
    question: str  # the student's message, already made safe for the provider
    history: list[ChatMessage]  # earlier turns, already made safe
    subject_id: UUID | None = None
    subjects: list[SubjectInfo] = field(default_factory=list)
    calendar: CalendarGateway | None = None  # the way to Google Calendar (the calendar server)
    guard: Guardrails | None = None  # NeMo rails; None when GUARDRAILS_ENABLED is off
    # What this conversation may search (see chatlogic.search_filter). "all" lets the agent pick a
    # course by name; "subject" and "materials" are the student's own limit and cannot be widened.
    scope_kind: str = "all"
    material_ids: tuple[UUID, ...] | None = None
    search_nothing: bool = False  # the chosen course or files no longer exist: search finds nothing
    # Text of the files attached to this conversation, already made safe to show the model.
    attachment_text: str = ""

    # --- filled while the run goes on -------------------------------------------------------
    guard_log: list[dict[str, Any]] = field(default_factory=list)  # what each rail decided (no text)
    guard_total: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)
    _source_numbers: dict[UUID, int] = field(default_factory=dict)
    pii: Counter[str] = field(default_factory=Counter)
    injections: int = 0
    hidden: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _turn: int = 0
    _step: int = 0
    # Tests (and anything running a node outside a graph) read events from here instead.
    sink: list[dict[str, Any]] | None = None
    # Hook so tests can replace the clock-free parts of tool calls if needed.
    on_event: Callable[[dict[str, Any]], None] | None = None

    # --- events ---------------------------------------------------------------------------
    def emit(self, event: dict[str, Any]) -> None:
        if self.sink is not None:
            self.sink.append(event)
            return
        try:
            get_stream_writer()(event)
        except Exception:  # outside a graph run there is no stream; drop the event
            logger.debug("event dropped (no stream): %s", event.get("type"))

    def next_turn(self) -> int:
        self._turn += 1
        return self._turn

    def next_step(self) -> int:
        self._step += 1
        return self._step

    @property
    def step_id(self) -> int:
        """The number of the step the running tool was given."""
        return self._step

    def resume_at(self, step: int, turn: int) -> None:
        """Continue numbering where a paused run stopped. `step` is the number BEFORE the tool
        that was waiting, so that tool, which runs again from its start, gets its old number back."""
        self._step, self._turn = step, turn

    def gateway(self) -> CalendarGateway:
        if self.calendar is None:
            raise RuntimeError("no calendar gateway in this context")
        return self.calendar

    def add_usage(self, message: Any) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        self.prompt_tokens += int(usage.get("input_tokens") or 0)
        self.completion_tokens += int(usage.get("output_tokens") or 0)

    # --- guardrails ---------------------------------------------------------------------------
    async def note_guard(self, decision: Decision, *, tool: str | None = None) -> None:
        """Show and keep what a rail did, when it did something. A rail that simply let the text
        through leaves no mark on screen; it is still counted in the run's totals."""
        self.guard_total += 1
        for key, n in decision.counts.items():
            if key.startswith("pii:"):
                self.pii[key[4:]] += n
            elif key == "injection":
                self.injections += n
            elif key == "hidden":
                self.hidden += n
        if not decision.noteworthy:
            return
        detail = {**decision.detail(), **({"tool": tool} if tool else {})}
        if len(self.guard_log) < 20:
            self.guard_log.append(detail)
        number = self.next_step()
        self.emit({
            "type": "step", "id": number, "agent": "guardrails", "tool": decision.rail,
            "summary": decision.summary()[:200], "status": "blocked" if decision.blocked else "done",
            "ms": decision.ms,
        })
        await self.record(
            node="guardrail", agent="guardrails", tool=decision.rail, args=detail,
            outcome=decision.action, ms=decision.ms,
        )

    # --- subjects -----------------------------------------------------------------------------
    def find_subject(self, name: str | None) -> SubjectInfo | None:
        """A subject the student named, matched ignoring case and, failing that, by containing
        the words. None if there is no clear match."""
        if not name or not name.strip():
            return None
        wanted = _norm(name)
        exact = [s for s in self.subjects if _norm(s.name) == wanted]
        if exact:
            return exact[0]
        partial = [s for s in self.subjects if wanted in _norm(s.name) or _norm(s.name) in wanted]
        return partial[0] if len(partial) == 1 else None

    def subject_names(self) -> str:
        return ", ".join(s.name for s in self.subjects) or "(none yet)"

    # --- searching the student's materials ----------------------------------------------------
    async def search(self, query: str, subject_id: UUID | None | str = "default") -> SearchResult:
        """Search the student's own materials. Sources found are numbered across the whole run, so
        a second search continues where the first stopped and the answer can cite either."""
        if self.search_nothing:
            self.emit({"type": "sources", "items": list(self.sources), "degraded": False})
            return SearchResult("", 0, 0, False)
        locked = self.scope_kind != "all"
        scope = self.subject_id if subject_id == "default" or locked else subject_id
        async with self.db.session() as session:
            found = await retrieve(
                session, self.models, query,
                subject_id=scope,  # type: ignore[arg-type]
                candidates=self.settings.retrieval_candidates,
                top_k=self.settings.retrieval_top_k,
                material_ids=self.material_ids,
            )
        numbered, added = self.register(found.passages)
        # Always sent after a search (even when nothing matched): the screen shows "no sources".
        self.emit({"type": "sources", "items": list(self.sources), "degraded": found.degraded})
        return SearchResult(
            format_numbered_sources(numbered) if numbered else "",
            added, len(found.passages), found.degraded,
        )

    def register(self, passages: list[Passage]) -> tuple[list[tuple[int, Passage, Prepared]], int]:
        """Number passages for citation (a passage seen before keeps its number) and make their
        text safe to show the model: hidden characters removed, instruction-like text quoted,
        personal data masked. Returns the numbered passages and how many were new."""
        mask = self.user.mask_personal_data
        numbered: list[tuple[int, Passage, Prepared]] = []
        added = 0
        for passage in passages:
            safe = prepare_untrusted(passage.text, mask_optional=mask)
            self.pii.update(safe.pii)
            self.injections += len(safe.injection)
            self.hidden += safe.hidden_removed
            number = self._source_numbers.get(passage.chunk_id)
            if number is None:
                number = len(self.sources) + 1
                self._source_numbers[passage.chunk_id] = number
                self.sources.append(
                    {
                        "n": number,
                        "material_id": str(passage.material_id),
                        "filename": passage.filename,
                        "page": passage.page,
                        "snippet": passage.text[:SNIPPET_CHARS],
                    }
                )
                added += 1
            numbered.append((number, passage, safe))
        return numbered, added

    def untrusted(self, value: str) -> str:
        """Text written by the student or taken from a document, made safe to show the model."""
        safe = prepare_untrusted(value, mask_optional=self.user.mask_personal_data)
        self.pii.update(safe.pii)
        self.injections += len(safe.injection)
        self.hidden += safe.hidden_removed
        return safe.text

    # --- recording --------------------------------------------------------------------------
    async def record(self, *, node: str, agent: str | None = None, tool: str | None = None,
                     args: Any = None, outcome: str | None = None, ms: int | None = None) -> None:
        """Add a step to agent_steps. Never allowed to break the answer."""
        try:
            async with self.db.session() as session:
                await runs.record_step(
                    session, self.run_id, node=node, agent=agent, tool=tool, args=args,
                    outcome=outcome, duration_ms=ms,
                )
        except Exception:
            logger.warning("could not record an agent step", exc_info=True)

    async def count_ready_materials(self) -> int:
        async with self.db.session() as session:
            return int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM materials WHERE deleted_at IS NULL AND status = 'ready'")
                    )
                ).scalar_one()
            )


_WORDS = re.compile(r"[\W_]+", re.UNICODE)


def _norm(value: str) -> str:
    return " ".join(_WORDS.sub(" ", value.casefold()).split())
