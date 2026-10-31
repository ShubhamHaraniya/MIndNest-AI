"""The guardrails engine: NeMo Guardrails runs four rails around every agent run.

    student's message --[input rail]--> router/agents
    model asks for a tool --[tool call rail]--> tool runs --[tool result rail]--> model reads it
    finished answer --[output rail]--> student

Each rail is a NeMo flow that calls one custom action. The actions below wrap the plain rule
functions in rules.py (which wrap mindnest_core.aisafety), so the same checks that always existed
now run through one place, leave one record each, and can be tested on their own.

Order of work for a message: the rules answer first and almost always settle it. Only when they
say "review" is the student's own model asked (judge.py), once, with a short timeout. If NeMo itself
fails for any reason the plain rules are run directly, so a rail is never silently skipped.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import GenerationOptions

from mindnest_agents.guardrails import config, judge, rules
from mindnest_agents.guardrails.judge import Judge
from mindnest_agents.guardrails.rules import Check

logger = logging.getLogger("mindnest.guardrails")
# NeMo logs every action at INFO; the student's text is in those lines, so keep them quiet.
for _name in ("nemoguardrails", "nemoguardrails.colang", "nemoguardrails.actions"):
    logging.getLogger(_name).setLevel(logging.WARNING)

INPUT, OUTPUT, TOOL_CALL, TOOL_RESULT = "input", "output", "tool_call", "tool_result"
_OFF = {"input": False, "output": False, "dialog": False, "retrieval": False, "tool_input": False, "tool_output": False}


@dataclass
class Decision:
    """What one rail decided. Holds labels and counts only, never the text it looked at (except
    `text`, the cleaned replacement, which is for the caller to use and not to store)."""

    rail: str
    action: str = "allow"  # allow | block | modify
    code: str = ""
    category: str = ""
    reasons: list[str] = field(default_factory=list)
    text: str | None = None
    judged: bool = False
    judge: str | None = None  # "stop" | "fine" | "unavailable"
    counts: dict[str, int] = field(default_factory=dict)
    ms: int = 0
    engine: str = "nemo"  # "rules" when NeMo failed and the plain rules ran instead

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def noteworthy(self) -> bool:
        """Worth showing and logging: something was stopped, changed, judged or flagged."""
        return self.action != "allow" or self.judged or bool(self.category)

    def summary(self) -> str:
        what = {"block": "stopped", "modify": "cleaned", "allow": "passed"}[self.action]
        bits = [what, *self.reasons[:3]]
        if self.judged:
            bits.append("second opinion")
        return " · ".join(bits)

    def detail(self) -> dict[str, Any]:
        return {
            "rail": self.rail, "action": self.action, "code": self.code, "category": self.category,
            "reasons": self.reasons, "judged": self.judged, "judge": self.judge, "ms": self.ms,
            "engine": self.engine,
        }


# --------------------------------------------------------------------------- per-call state

@dataclass
class _Call:
    judge: Judge | None
    timeout: float
    user_text: str = ""
    allowed: set[str] | None = None
    mask_optional: bool = True
    canary: str | None = None


_CALLS: dict[str, _Call] = {}


async def _settle(check: Check, text: str, call: _Call | None) -> dict[str, Any]:
    """Turn a "review" into a final answer by asking the student's model, if there is one."""
    out = check.as_dict()
    if check.action != "review":
        out["judged"], out["judge"] = False, None
        return out
    label: str | None = None
    if call is not None and call.judge is not None:
        try:
            async with asyncio.timeout(call.timeout):
                reply = await call.judge(judge.judge_system(check.category), judge.judge_user(text))
            label = judge.read_label(reply, check.category)
        except Exception as exc:  # the judge is best effort; a failure is not a student's problem
            logger.info("guardrail judge unavailable (%s)", type(exc).__name__)
    if label == "stop":
        out.update(action="block", judged=True, judge="stop")
    elif label == "fine":
        out.update(action="allow", judged=True, judge="fine")
    else:  # no model, no answer, or an answer we cannot read: use the rule's own default
        out.update(action=check.fallback, judged=False, judge="unavailable")
    return out


# --------------------------------------------------------------------------- NeMo custom actions

async def mn_input(context: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = context or {}
    text = str(ctx.get("user_message") or "")
    return await _settle(rules.check_input(text), text, _CALLS.get(str(ctx.get("mn_call"))))


async def mn_tool_call(calls: Any = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = context or {}
    call = _CALLS.get(str(ctx.get("mn_call")))
    user_text = call.user_text if call else ""
    allowed = call.allowed if call else None
    for item in calls or []:
        function = (item or {}).get("function") or {}
        args = function.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                return {**Check("block", rules.TOOL_BLOCKED, "tool", ["unreadable_arguments"]).as_dict(), "judged": False}
        check = rules.check_tool_call(str(function.get("name") or ""), args, user_text, allowed)
        if check.action != "allow":
            return {**check.as_dict(), "judged": False}
    return {**Check().as_dict(), "judged": False}


async def mn_tool_result(text: str = "", name: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
    call = _CALLS.get(str((context or {}).get("mn_call")))
    check = rules.check_tool_result(str(text), mask_optional=call.mask_optional if call else True)
    return {**check.as_dict(), "judged": False}


async def mn_output(context: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = context or {}
    call = _CALLS.get(str(ctx.get("mn_call")))
    check, _safe = rules.check_output(
        str(ctx.get("bot_message") or ""), call.canary if call else None, call.mask_optional if call else False
    )
    return {**check.as_dict(), "judged": False}


ACTIONS = {
    "mn_input": mn_input, "mn_tool_call": mn_tool_call,
    "mn_tool_result": mn_tool_result, "mn_output": mn_output,
}


# --------------------------------------------------------------------------- the engine

class Guardrails:
    """One shared instance per process. It holds no per-student state: everything about one check
    travels in the call itself, so concurrent chats cannot see each other's text."""

    def __init__(self, *, judge_timeout: float = 8.0) -> None:
        self.judge_timeout = judge_timeout
        self._rails: LLMRails | None = None

    # NeMo is built on first use (about 150 ms) so importing this module stays free.
    def _engine(self) -> LLMRails:
        if self._rails is None:
            rails = LLMRails(RailsConfig.from_content(colang_content=config.COLANG, yaml_content=config.YAML))
            for name, action in ACTIONS.items():
                rails.register_action(action, name)
            self._rails = rails
        return self._rails

    def warm(self) -> None:
        self._engine()

    async def _run(self, call: _Call, messages: list[dict[str, Any]], rail: str, var: str, **context: Any) -> dict[str, Any]:
        token = uuid.uuid4().hex
        _CALLS[token] = call
        try:
            options = GenerationOptions(rails={**_OFF, rail_flag(rail): True}, output_vars=[var])
            response = await self._engine().generate_async(
                messages=[{"role": "context", "content": {"mn_call": token, **context}}, *messages], options=options
            )
            data = (response.output_data or {}).get(var)  # type: ignore[union-attr]
            if not isinstance(data, dict):
                raise RuntimeError("the rail returned no verdict")
            return data
        finally:
            _CALLS.pop(token, None)

    # ----- the four rails

    async def check_input(
        self, text: str, *, judge: Judge | None = None, mask_optional: bool = True
    ) -> Decision:
        started = time.perf_counter()
        call = _Call(judge, self.judge_timeout, user_text=text, mask_optional=mask_optional)
        engine = "nemo"
        try:
            data = await self._run(call, [{"role": "user", "content": text}], INPUT, "mn_in")
        except Exception:
            logger.warning("NeMo input rail failed; ran the plain rules", exc_info=True)
            engine = "rules"
            token = uuid.uuid4().hex
            _CALLS[token] = call
            try:
                data = await _settle(rules.check_input(text), text, call)
            finally:
                _CALLS.pop(token, None)
        return _decision(INPUT, data, started, engine)

    async def check_tool_call(
        self, name: str, args: Any, *, user_text: str, allowed: set[str] | None = None
    ) -> Decision:
        started = time.perf_counter()
        call = _Call(None, 0, user_text=user_text, allowed=allowed)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_text or " "},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call", "type": "function", "function": {"name": name, "arguments": json.dumps(args, default=str)}}
            ]},
        ]
        engine = "nemo"
        try:
            data = await self._run(call, messages, TOOL_CALL, "mn_tc")
        except Exception:
            logger.warning("NeMo tool call rail failed; ran the plain rules", exc_info=True)
            engine = "rules"
            data = rules.check_tool_call(name, args, user_text, allowed).as_dict()
        return _decision(TOOL_CALL, data, started, engine)

    async def check_tool_result(self, name: str, text: str, *, mask_optional: bool = True) -> Decision:
        started = time.perf_counter()
        call = _Call(None, 0, mask_optional=mask_optional)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": " "},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call", "type": "function", "function": {"name": name, "arguments": "{}"}}
            ]},
            {"role": "tool", "content": text, "name": name, "tool_call_id": "call"},
        ]
        engine = "nemo"
        try:
            data = await self._run(call, messages, TOOL_RESULT, "mn_tr")
        except Exception:
            logger.warning("NeMo tool result rail failed; ran the plain rules", exc_info=True)
            engine = "rules"
            data = rules.check_tool_result(text, mask_optional=mask_optional).as_dict()
        return _decision(TOOL_RESULT, data, started, engine)

    async def check_output(self, text: str, *, canary: str | None, mask_optional: bool = False) -> Decision:
        started = time.perf_counter()
        call = _Call(None, 0, canary=canary, mask_optional=mask_optional)
        messages = [{"role": "user", "content": " "}, {"role": "assistant", "content": text}]
        engine = "nemo"
        try:
            data = await self._run(call, messages, OUTPUT, "mn_out")
        except Exception:
            logger.warning("NeMo output rail failed; ran the plain rules", exc_info=True)
            engine = "rules"
            data = rules.check_output(text, canary, mask_optional)[0].as_dict()
        return _decision(OUTPUT, data, started, engine)


def rail_flag(rail: str) -> str:
    return {INPUT: "input", OUTPUT: "output", TOOL_CALL: "tool_output", TOOL_RESULT: "tool_input"}[rail]


def _decision(rail: str, data: dict[str, Any], started: float, engine: str) -> Decision:
    return Decision(
        rail=rail, action=str(data.get("action", "allow")), code=str(data.get("code", "")),
        category=str(data.get("category", "")), reasons=list(data.get("reasons", [])),
        text=data.get("text"), judged=bool(data.get("judged")), judge=data.get("judge"),
        counts=dict(data.get("counts") or {}),
        ms=int((time.perf_counter() - started) * 1000), engine=engine,
    )


_shared: Guardrails | None = None


def get_guardrails(judge_timeout: float = 8.0) -> Guardrails:
    global _shared
    if _shared is None:
        _shared = Guardrails(judge_timeout=judge_timeout)
    return _shared
