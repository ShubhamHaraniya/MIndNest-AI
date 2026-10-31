"""The scores. Plain functions over finished runs, so they can be tested without a server or a model.

What is measured, and how:

routing        did the orchestrator pick the agents the case expects (exact set, and first agent)
tools          did the agents use the tools the case needs, and avoid the ones it forbids
task success   did every rule the case lists hold (no error, cards, words in the answer, approval)
guardrails     did the input rail stop what it should and let the rest through (precision, recall)
grounding      are factual answers backed by the student's own notes: citation rate (rules) and
               faithfulness (Ragas, judged by a model)
topic          do replies to off-topic requests stay inside what a study assistant is for (judged)
speed, cost    time to the first word, time to finish, tokens
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from mindnest_agents.evaluation.cases import Case
from mindnest_agents.evaluation.trace import RunRecord

import re

_CITATION = re.compile(r"\[(\d{1,2})\]")


@dataclass
class CaseResult:
    case: Case
    record: RunRecord
    failures: list[str] = field(default_factory=list)
    faithfulness: float | None = None
    topic: float | None = None
    judge_error: str | None = None

    @property
    def passed(self) -> bool:
        return self.record.status != "skipped" and not self.failures

    def as_dict(self) -> dict[str, Any]:
        r = self.record
        return {
            "id": self.case.id, "category": self.case.category, "status": r.status,
            "passed": self.passed, "failures": self.failures, "skipped_because": r.skipped_because,
            "agents": r.agents, "tools": r.tools, "cards": r.cards, "guard": r.guard,
            "error": r.error, "total_ms": r.total_ms, "first_token_ms": r.first_token_ms,
            "tokens": r.prompt_tokens + r.completion_tokens, "run_id": r.run_id,
            "faithfulness": self.faithfulness, "topic": self.topic, "judge_error": self.judge_error,
            "answer": r.answer[:1200],
        }


# --------------------------------------------------------------------------- per-case checks

_LOOKALIKES = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',  # curly quotes
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",  # dashes and hyphens
    "\u00a0": " ", "\u202f": " ",  # non-breaking spaces
})


def _plain(text: str) -> str:
    """Case, curly quotes, special hyphens and non-breaking spaces folded, so a model writing
    "don\u2019t" or "semi\u2011permeable" still matches a rule written with plain characters."""
    return text.translate(_LOOKALIKES).casefold()


def _has(text: str, needle: str) -> bool:
    return _plain(needle) in _plain(text)


def check_case(case: Case, rec: RunRecord) -> list[str]:
    """Every rule the case lists, as a list of short failure reasons (empty = success)."""
    if rec.status == "skipped":
        return []
    exp = case.expect
    out: list[str] = []
    wanted_error = exp.get("error")
    if rec.status == "error" and rec.error != wanted_error:
        out.append(f"error:{rec.error}")
    if wanted_error and rec.error != wanted_error:
        out.append(f"expected error {wanted_error}")
    if "agents" in exp:
        if set(rec.agents) != set(exp["agents"]):
            out.append(f"route:{'+'.join(rec.agents) or 'none'}!={'+'.join(exp['agents']) or 'none'}")
    for tool in exp.get("tools", []):
        if tool not in rec.tools:
            out.append(f"tool_missing:{tool}")
    for tool in exp.get("forbid_tools", []):
        if tool in rec.tools:
            out.append(f"tool_forbidden:{tool}")
    for card in exp.get("cards", []):
        if card not in rec.cards:
            out.append(f"card_missing:{card}")
    answer = rec.answer
    anys = exp.get("answer_any", [])
    if anys and not any(_has(answer, a) for a in anys):
        out.append("answer_lacks_any")
    for needle in exp.get("answer_all", []):
        if not _has(answer, needle):
            out.append(f"answer_lacks:{needle}")
    for needle in exp.get("answer_none", []):
        if _has(answer, needle):
            out.append(f"answer_contains:{needle}")
    guard = exp.get("guard")
    if guard == "block" and not rec.blocked_by_input_rail:
        out.append("guard:not_blocked")
    if guard == "allow" and rec.blocked_by_input_rail:
        out.append("guard:wrongly_blocked")
    if "awaiting_approval" in exp and rec.awaiting_approval != bool(exp["awaiting_approval"]):
        out.append("approval_state")
    if exp.get("cites") and not _CITATION.search(answer):
        out.append("no_citation")
    if "max_ms" in exp and rec.total_ms > int(exp["max_ms"]):
        out.append(f"slow:{rec.total_ms}ms")
    return out


# --------------------------------------------------------------------------- aggregate scores

def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return round(ordered[k], 1)


def _ran(results: list[CaseResult]) -> list[CaseResult]:
    return [r for r in results if r.record.status != "skipped"]


def routing(results: list[CaseResult]) -> dict[str, Any]:
    rows = [r for r in _ran(results) if "agents" in r.case.expect and r.record.status == "ok"]
    exact = sum(set(r.record.agents) == set(r.case.expect["agents"]) for r in rows)
    first = sum(
        bool(r.record.agents) and bool(r.case.expect["agents"]) and r.record.agents[0] == r.case.expect["agents"][0]
        for r in rows
    )
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        if r.case.expect["agents"]:
            confusion[r.case.expect["agents"][0]][r.record.agents[0] if r.record.agents else "none"] += 1
    return {
        "cases": len(rows), "exact": _rate(exact, len(rows)), "first_agent": _rate(first, len(rows)),
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def tools(results: list[CaseResult]) -> dict[str, Any]:
    needed = [(r, t) for r in _ran(results) if r.record.status == "ok" for t in r.case.expect.get("tools", [])]
    used = sum(t in r.record.tools for r, t in needed)
    forbidden = [(r, t) for r in _ran(results) for t in r.case.expect.get("forbid_tools", [])]
    violations = sum(t in r.record.tools for r, t in forbidden)
    calls = [len(r.record.tools) for r in _ran(results) if r.record.status == "ok"]
    failed = sum(len(r.record.tool_failures) for r in _ran(results))
    return {
        "expected_calls": len(needed), "recall": _rate(used, len(needed)),
        "forbidden_checks": len(forbidden), "forbidden_used": violations,
        "tool_calls_per_run": round(sum(calls) / len(calls), 2) if calls else None, "tool_failures": failed,
    }


def task_success(results: list[CaseResult]) -> dict[str, Any]:
    ran = _ran(results)
    by_category: dict[str, list[bool]] = defaultdict(list)
    for r in ran:
        by_category[r.case.category].append(r.passed)
    reasons = Counter(f.split(":")[0] for r in ran for f in r.failures)
    return {
        "cases": len(ran), "passed": sum(r.passed for r in ran),
        "rate": _rate(sum(r.passed for r in ran), len(ran)),
        "by_category": {c: {"cases": len(v), "rate": _rate(sum(v), len(v))} for c, v in sorted(by_category.items())},
        "failure_kinds": dict(reasons.most_common()),
        "skipped": len(results) - len(ran),
    }


def guardrails(results: list[CaseResult]) -> dict[str, Any]:
    """Confusion matrix of the input rail over the cases that state an expectation."""
    tp = fn = fp = tn = 0
    for r in _ran(results):
        want = r.case.expect.get("guard")
        if want not in ("block", "allow") or r.record.status == "error":
            continue
        got = r.record.blocked_by_input_rail
        if want == "block":
            tp, fn = tp + got, fn + (not got)
        else:
            fp, tn = fp + got, tn + (not got)
    judged = sum(r.record.judged for r in _ran(results))
    tool_blocked = sum(any(g["rail"] == "tool_call" and g["status"] == "blocked" for g in r.record.guard) for r in _ran(results))
    return {
        "true_block": tp, "missed": fn, "false_block": fp, "true_allow": tn,
        "recall": _rate(tp, tp + fn), "precision": _rate(tp, tp + fp),
        "false_block_rate": _rate(fp, fp + tn), "second_opinions": judged, "tool_calls_blocked": tool_blocked,
    }


def grounding(results: list[CaseResult]) -> dict[str, Any]:
    cited = [r for r in _ran(results) if r.case.expect.get("cites")]
    with_citation = sum(bool(_CITATION.search(r.record.answer)) for r in cited)
    valid = 0
    for r in cited:
        numbers = {int(n) for n in _CITATION.findall(r.record.answer)}
        have = {int(s.get("n", 0)) for s in r.record.sources}
        valid += bool(numbers) and numbers <= have
    scores = [r.faithfulness for r in results if r.faithfulness is not None]
    return {
        "citation_cases": len(cited), "citation_rate": _rate(with_citation, len(cited)),
        "citations_all_real": _rate(valid, len(cited)),
        "faithfulness_cases": len(scores),
        "faithfulness": round(sum(scores) / len(scores), 4) if scores else None,
    }


def topic(results: list[CaseResult]) -> dict[str, Any]:
    scores = [r.topic for r in results if r.topic is not None]
    return {"cases": len(scores), "adherence": round(sum(scores) / len(scores), 4) if scores else None}


def speed_and_cost(results: list[CaseResult]) -> dict[str, Any]:
    ok = [r.record for r in _ran(results) if r.record.status == "ok"]
    totals = [float(r.total_ms) for r in ok]
    firsts = [float(r.first_token_ms) for r in ok if r.first_token_ms is not None]
    tokens = [r.prompt_tokens + r.completion_tokens for r in ok if r.prompt_tokens or r.completion_tokens]
    per_agent: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        if r.agents:
            per_agent[r.agents[0]].append(float(r.total_ms))
    return {
        "runs": len(ok),
        "first_token_ms": {"p50": percentile(firsts, 50), "p95": percentile(firsts, 95)},
        "total_ms": {"p50": percentile(totals, 50), "p95": percentile(totals, 95)},
        "tokens_per_run": round(sum(tokens) / len(tokens)) if tokens else None,
        "tokens_total": sum(tokens),
        "by_first_agent_p50_ms": {a: percentile(v, 50) for a, v in sorted(per_agent.items())},
    }


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    return {
        "cases": len(results), "routing": routing(results), "tools": tools(results),
        "task_success": task_success(results), "guardrails": guardrails(results),
        "grounding": grounding(results), "topic": topic(results), "speed_and_cost": speed_and_cost(results),
    }
