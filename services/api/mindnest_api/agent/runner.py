"""Running the graph for one student message and turning what happens into events.

`Turn` collects what the route needs to save afterwards (the answer, sources, steps, cards), no
matter whether the run finished, failed or was stopped half-way."""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mindnest_agents.checkpoint import open_checkpointer
from mindnest_agents.errors import AgentError
from mindnest_agents.tracing import RunTracing
from langgraph.types import Command

from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.graph import build_graph

logger = logging.getLogger("mindnest.agent")


@dataclass
class Turn:
    texts: dict[int, str] = field(default_factory=dict)
    discarded: set[int] = field(default_factory=set)
    sources: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    steps: dict[int, dict[str, Any]] = field(default_factory=dict)
    cards: list[dict[str, Any]] = field(default_factory=list)
    route: dict[str, Any] | None = None
    # Changes to cards shown earlier (a proposal the student has now approved or declined).
    card_updates: list[dict[str, Any]] = field(default_factory=list)
    # Set when the run paused to ask the student: {"proposal": ..., "cursor": {"step", "turn"}}.
    interrupt: dict[str, Any] | None = None

    def apply(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "token":
            turn = int(event.get("turn", 0))
            self.texts[turn] = self.texts.get(turn, "") + str(event.get("text", ""))
        elif kind == "discard":
            self.discarded.add(int(event.get("turn", 0)))
        elif kind == "sources":
            self.sources = list(event.get("items", []))
            self.degraded = bool(event.get("degraded"))
        elif kind == "step":
            self.steps[int(event["id"])] = {k: v for k, v in event.items() if k != "type"}
        elif kind == "card":
            self.cards.append({"kind": event.get("kind"), "data": event.get("data", {})})
        elif kind == "card_update":
            self.card_updates.append({k: v for k, v in event.items() if k != "type"})
        elif kind == "route":
            self.route = {k: v for k, v in event.items() if k != "type"}

    @property
    def answer(self) -> str:
        return "".join(t for n, t in self.texts.items() if n not in self.discarded)

    def step_list(self) -> list[dict[str, Any]]:
        return [self.steps[i] for i in sorted(self.steps)]


def _asked(payload: Any) -> dict[str, Any] | None:
    """The question a paused run is asking, from a graph "updates" payload (None if it is not one)."""
    if not isinstance(payload, dict):
        return None
    found = payload.get("__interrupt__")
    if not found:
        return None
    first = found[0] if isinstance(found, (list, tuple)) else found
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else None


async def stream_run(
    ctx: AgentContext, turn: Turn, tracing: RunTracing, thread: str,
    resume: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield the events of one run, in order, and record them in `turn`.

    With `resume`, the run continues from where it paused for the student's decision instead of
    starting over. If it pauses again (or for the first time) `turn.interrupt` is set and a
    proposal card event is the last thing yielded."""
    settings = ctx.settings
    config: dict[str, Any] = {
        **tracing.config(),
        "run_id": ctx.run_id,
        "recursion_limit": settings.agent_max_steps,
        "configurable": {"thread_id": thread},
    }
    try:
        async with asyncio.timeout(settings.agent_run_timeout_seconds):
            async with open_checkpointer(settings.database_url, ctx.user.id) as saver:
                if resume is None:
                    # A new message starts a fresh run on this conversation's thread.
                    await saver.adelete_thread(thread)
                graph = build_graph(ctx, saver)
                start: Any = (
                    {"step_index": 0, "plan": [], "results": [], "user_text": ctx.question, "blocked": False}
                    if resume is None else Command(resume=resume)
                )
                # subgraphs=True: the agents are subgraphs, and their events must come through too.
                async for _namespace, mode, payload in graph.astream(
                    start, config, stream_mode=["custom", "updates"], subgraphs=True,
                ):
                    if mode == "custom" and isinstance(payload, dict):
                        turn.apply(payload)
                        yield payload
                    elif mode == "updates":
                        asked = _asked(payload)
                        if asked is not None and turn.interrupt is None:
                            proposal = dict(asked.get("proposal") or {})
                            # The tool that is waiting runs again from its start when resumed, so
                            # numbering restarts one step before it.
                            turn.interrupt = {
                                "proposal": proposal,
                                "cursor": {"step": max(ctx.step_id - 1, 0), "turn": ctx._turn},
                            }
                            card = {
                                "type": "card", "kind": str(asked.get("kind") or "calendar_proposal"),
                                "data": {**proposal, "status": "pending", "run_id": str(ctx.run_id)},
                            }
                            turn.apply(card)
                            yield card
    except TimeoutError as exc:
        raise AgentError("timeout") from exc
