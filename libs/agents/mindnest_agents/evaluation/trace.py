"""Turning the chat's event stream into one record per run, the same way for the live runner and
for tests."""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunRecord:
    status: str = "ok"  # ok | error | skipped
    error: str | None = None
    skipped_because: str | None = None
    run_id: str | None = None
    agents: list[str] = field(default_factory=list)
    shortcut: bool = False
    tools: list[str] = field(default_factory=list)  # tools the agents used (not safety checks)
    tool_failures: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    guard: list[dict[str, Any]] = field(default_factory=list)  # {"rail", "status", "summary"}
    awaiting_approval: bool = False
    total_ms: int = 0
    first_token_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def blocked_by_input_rail(self) -> bool:
        return any(g["rail"] == "input" and g["status"] == "blocked" for g in self.guard)

    @property
    def judged(self) -> bool:
        return any("second opinion" in g.get("summary", "") for g in self.guard)


def parse_sse_text(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        name, data = "", ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if name and data:
            events.append((name, json.loads(data)))
    return events


def record_from_events(
    events: list[tuple[str, dict[str, Any]]], *, total_ms: int = 0, first_token_ms: int | None = None
) -> RunRecord:
    rec = RunRecord(total_ms=total_ms, first_token_ms=first_token_ms)
    texts: dict[int, str] = {}
    discarded: set[int] = set()
    steps: dict[int, dict[str, Any]] = {}
    safe_text: str | None = None
    final_text: str | None = None
    for name, data in events:
        if name == "meta":
            rec.run_id = data.get("run_id")
        elif name == "route":
            rec.agents = list(data.get("agents", []))
            rec.shortcut = bool(data.get("shortcut"))
        elif name == "step":
            steps[int(data["id"])] = data
        elif name == "token":
            turn = int(data.get("turn", 0))
            texts[turn] = texts.get(turn, "") + str(data.get("text", ""))
        elif name == "discard":
            discarded.add(int(data.get("turn", 0)))
        elif name == "card":
            rec.cards.append(str(data.get("kind")))
        elif name == "sources":
            rec.sources = list(data.get("items", []))
        elif name == "safety":
            safe_text = str(data.get("text", ""))
        elif name == "final":
            final_text = str(data.get("text", ""))  # the answer as the student finally sees it
        elif name == "error":
            rec.status, rec.error = "error", str(data.get("code"))
        elif name == "done":
            rec.awaiting_approval = bool(data.get("awaiting_approval"))
            usage = data.get("usage") or {}
            rec.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            rec.completion_tokens = int(usage.get("completion_tokens") or 0)
    streamed = safe_text if safe_text is not None else "".join(
        t for n, t in sorted(texts.items()) if n not in discarded
    )
    rec.answer = final_text if final_text is not None else streamed
    for step in sorted(steps.values(), key=lambda s: int(s["id"])):
        if step.get("agent") == "guardrails":
            rec.guard.append(
                {"rail": step.get("tool"), "status": step.get("status"), "summary": step.get("summary", "")}
            )
        elif step.get("tool"):
            rec.tools.append(str(step["tool"]))
            if step.get("status") == "failed":
                rec.tool_failures.append(str(step["tool"]))
    return rec
