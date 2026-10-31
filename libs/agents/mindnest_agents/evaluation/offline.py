"""Checking the guardrails alone: no server, no model, no network.

Each case's message goes through the input rail exactly as it would in the chat, with no second
opinion available. So this measures the rules and their safe defaults, and it is fast and exact
enough to run on every change (a message that should be stopped but is not shows up at once)."""

from mindnest_agents.evaluation.cases import Case
from mindnest_agents.evaluation.metrics import CaseResult, check_case
from mindnest_agents.evaluation.trace import RunRecord
from mindnest_agents.guardrails import Guardrails, refusal_text


async def run_offline(cases: list[Case], guard: Guardrails | None = None) -> list[CaseResult]:
    guard = guard or Guardrails()
    results: list[CaseResult] = []
    for case in cases:
        decision = await guard.check_input(case.message)
        rec = RunRecord(total_ms=decision.ms)
        if decision.noteworthy:
            rec.guard.append(
                {"rail": "input", "status": "blocked" if decision.blocked else "done", "summary": decision.summary()}
            )
        if decision.blocked:
            rec.answer = refusal_text(decision.code, case.message)
        # Only what a rail can decide is checked here; routing and tools need a model.
        shown = Case(
            case.id, case.category, case.message, case.subject, case.requires, case.writes, True,
            _offline_expectation(case.expect),
        )
        results.append(CaseResult(case=shown, record=rec, failures=check_case(shown, rec)))
    return results


def _offline_expectation(expect: dict[str, object]) -> dict[str, object]:
    """What can be checked without a model. `guard_offline` replaces `guard` where the live answer
    depends on the second opinion (a takeover attempt is let through when nobody can judge it; the
    other layers still protect: documents are quoted, answers are cleaned, changes need approval)."""
    kept = {k: v for k, v in expect.items() if k in ("guard", "answer_any", "answer_all", "answer_none")}
    if "guard_offline" in expect:
        kept["guard"] = expect["guard_offline"]
    return kept
