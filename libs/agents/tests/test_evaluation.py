"""The evaluation tools: the dataset, the scores, the reports, the judges and the HTTP runner."""

import json
from pathlib import Path

import httpx
import pytest
from mindnest_agents.evaluation import Case, check_case, load_cases, record_from_events, summarize
from mindnest_agents.evaluation.client import EvalClient, EvalError
from mindnest_agents.evaluation.metrics import CaseResult, percentile
from mindnest_agents.evaluation.offline import run_offline
from mindnest_agents.evaluation.report import build_report, push_langsmith_feedback, to_markdown, write_report
from mindnest_agents.evaluation.trace import RunRecord, parse_sse_text

DATASET = Path(__file__).resolve().parents[3] / "evals" / "agents" / "agent_v1.jsonl"
CORPUS = DATASET.parent / "corpus"
AGENTS = {"direct", "study", "quiz", "materials", "planner", "assignment", "calendar"}


# ----------------------------------------------------------------------------- the dataset


def test_the_dataset_is_valid_and_covers_every_agent() -> None:
    cases = load_cases(DATASET)
    assert len(cases) >= 45
    assert len({c.id for c in cases}) == len(cases)
    named = {a for c in cases for a in c.expect.get("agents", [])}
    assert named == AGENTS
    assert {"study", "direct", "quiz", "materials", "planner", "assignment", "calendar", "guardrail", "off_topic"} <= {
        c.category for c in cases
    }
    for case in cases:
        assert set(case.expect.get("agents", [])) <= AGENTS, case.id


def test_offline_cases_only_ask_what_a_rail_can_answer() -> None:
    cases = [c for c in load_cases(DATASET) if c.offline]
    assert len(cases) >= 12
    for case in cases:
        assert "guard" in case.expect, case.id
        assert not {"agents", "tools", "cards"} & set(case.expect), case.id


def test_the_corpus_holds_the_facts_the_cases_ask_about() -> None:
    text = " ".join(p.read_text(encoding="utf-8") for p in CORPUS.glob("*.txt"))
    for fact in ("RuBisCO", "PMAT", "Okazaki", "cytoplasm", "haploid", "denature", "evil@example.com"):
        assert fact in text
    assert "French Revolution" not in text  # the unanswerable case really is unanswerable


def test_a_bad_case_file_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "x.jsonl"
    bad.write_text('{"id": "a", "category": "c", "message": "m", "expect": {"nonsense": 1}}\n')
    with pytest.raises(ValueError, match="unknown expectation"):
        load_cases(bad)
    bad.write_text('{"id": "a", "category": "c", "message": "m"}\n{"id": "a", "category": "c", "message": "m"}\n')
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(bad)


# ----------------------------------------------------------------------------- reading a run


def _events() -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    return [
        ("meta", {"run_id": "r1"}),
        ("route", {"agents": ["study"], "shortcut": False}),
        ("step", {"id": 1, "agent": "study", "tool": None, "status": "done"}),
        ("step", {"id": 2, "agent": "study", "tool": "search_materials", "status": "running"}),
        ("step", {"id": 2, "agent": "study", "tool": "search_materials", "status": "done"}),
        ("step", {"id": 3, "agent": "guardrails", "tool": "tool_result", "status": "done", "summary": "cleaned"}),
        ("token", {"turn": 1, "text": "draft"}),
        ("discard", {"turn": 1}),
        ("token", {"turn": 2, "text": "RuBisCO fixes CO2 [1]."}),
        ("sources", {"items": [{"n": 1, "snippet": "RuBisCO attaches CO2"}], "degraded": False}),
        ("card", {"kind": "materials", "data": {}}),
        ("done", {"message_id": "m", "awaiting_approval": False, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}),
    ]


def test_a_stream_becomes_one_record() -> None:
    rec = record_from_events(_events(), total_ms=900, first_token_ms=300)
    assert rec.agents == ["study"] and rec.tools == ["search_materials"] and rec.cards == ["materials"]
    assert rec.answer == "RuBisCO fixes CO2 [1]."  # the retracted draft is not part of it
    assert rec.guard == [{"rail": "tool_result", "status": "done", "summary": "cleaned"}]
    assert (rec.prompt_tokens, rec.completion_tokens, rec.run_id) == (100, 20, "r1")


def test_a_cleaned_answer_replaces_what_was_streamed() -> None:
    rec = record_from_events([*_events()[:-1], ("safety", {"text": "clean text", "changes": ["image"]})])
    assert rec.answer == "clean text"


def test_a_raw_event_stream_text_is_parsed() -> None:
    body = 'event: meta\ndata: {"run_id": "x"}\n\nevent: done\ndata: {"message_id": null}\n\n'
    assert [n for n, _ in parse_sse_text(body)] == ["meta", "done"]


def test_an_error_event_marks_the_run() -> None:
    rec = record_from_events([("error", {"code": "invalid_key"})])
    assert rec.status == "error" and rec.error == "invalid_key"


# ----------------------------------------------------------------------------- the checks


def _case(**expect) -> Case:  # type: ignore[no-untyped-def]
    return Case("c", "study", "q", expect=expect)


def _rec(**kw) -> RunRecord:  # type: ignore[no-untyped-def]
    return RunRecord(**{"agents": ["study"], "tools": ["search_materials"], "answer": "RuBisCO [1]", **kw})


def test_a_case_passes_when_every_rule_holds() -> None:
    case = _case(agents=["study"], tools=["search_materials"], answer_any=["rubisco"], cites=True)
    assert check_case(case, _rec()) == []


@pytest.mark.parametrize(
    ("expect", "record", "failure"),
    [
        ({"agents": ["quiz"]}, _rec(), "route:study!=quiz"),
        ({"tools": ["create_quiz"]}, _rec(), "tool_missing:create_quiz"),
        ({"forbid_tools": ["add_task"]}, _rec(tools=["add_task"]), "tool_forbidden:add_task"),
        ({"cards": ["quiz"]}, _rec(), "card_missing:quiz"),
        ({"answer_any": ["zzz"]}, _rec(), "answer_lacks_any"),
        ({"answer_none": ["rubisco"]}, _rec(), "answer_contains:rubisco"),
        ({"cites": True}, _rec(answer="no citation"), "no_citation"),
        ({"awaiting_approval": True}, _rec(), "approval_state"),
        ({"max_ms": 10}, _rec(total_ms=50), "slow:50ms"),
        ({}, RunRecord(status="error", error="timeout"), "error:timeout"),
        ({"guard": "block"}, _rec(), "guard:not_blocked"),
        ({"guard": "allow"}, _rec(guard=[{"rail": "input", "status": "blocked", "summary": "stopped"}]), "guard:wrongly_blocked"),
    ],
)
def test_each_rule_reports_its_own_failure(expect: dict, record: RunRecord, failure: str) -> None:  # type: ignore[type-arg]
    assert failure in check_case(_case(**expect), record)


def test_a_skipped_case_neither_passes_nor_fails() -> None:
    rec = RunRecord(status="skipped", skipped_because="x")
    assert check_case(_case(agents=["quiz"]), rec) == []
    assert not CaseResult(_case(), rec).passed


# ----------------------------------------------------------------------------- the scores


def _results() -> list[CaseResult]:
    def result(case: Case, rec: RunRecord) -> CaseResult:
        return CaseResult(case, rec, check_case(case, rec))

    blocked = [{"rail": "input", "status": "blocked", "summary": "stopped"}]
    return [
        result(Case("a", "study", "q", expect={"agents": ["study"], "tools": ["search_materials"], "cites": True}),
               _rec(total_ms=1000, first_token_ms=200, sources=[{"n": 1}], prompt_tokens=100, completion_tokens=50)),
        result(Case("b", "routing", "q", expect={"agents": ["quiz"]}), _rec(total_ms=3000, first_token_ms=400)),
        result(Case("c", "guardrail", "q", expect={"guard": "block"}), RunRecord(guard=blocked, total_ms=50)),
        result(Case("d", "guardrail", "q", expect={"guard": "block"}), RunRecord(total_ms=50)),
        result(Case("e", "guardrail", "q", expect={"guard": "allow"}), RunRecord(guard=blocked, total_ms=50)),
        result(Case("f", "guardrail", "q", expect={"guard": "allow"}), RunRecord(total_ms=50)),
        result(Case("g", "calendar", "q", requires=["google"]), RunRecord(status="skipped", skipped_because="no google")),
    ]


def test_the_summary_scores_are_computed_from_the_runs() -> None:
    s = summarize(_results())
    assert s["task_success"]["cases"] == 6 and s["task_success"]["skipped"] == 1
    assert s["task_success"]["passed"] == 3  # a, c, f
    assert s["routing"]["cases"] == 2 and s["routing"]["exact"] == 0.5
    assert s["routing"]["confusion"] == {"study": {"study": 1}, "quiz": {"study": 1}}
    assert s["tools"]["recall"] == 1.0
    g = s["guardrails"]
    assert (g["true_block"], g["missed"], g["false_block"], g["true_allow"]) == (1, 1, 1, 1)
    assert g["recall"] == 0.5 and g["precision"] == 0.5 and g["false_block_rate"] == 0.5
    assert s["grounding"]["citation_rate"] == 1.0 and s["grounding"]["citations_all_real"] == 1.0
    assert s["speed_and_cost"]["tokens_per_run"] == 150


def test_percentiles() -> None:
    assert percentile([], 50) is None
    assert percentile([10, 20, 30, 40], 50) == 20 and percentile([10, 20, 30, 40], 95) == 40


def test_judge_scores_are_averaged_when_present() -> None:
    results = _results()
    results[0].faithfulness, results[1].faithfulness, results[0].topic = 1.0, 0.5, 0.0
    s = summarize(results)
    assert s["grounding"]["faithfulness"] == 0.75 and s["grounding"]["faithfulness_cases"] == 2
    assert s["topic"]["adherence"] == 0.0


def test_a_citation_to_a_source_that_does_not_exist_is_caught() -> None:
    case = Case("x", "study", "q", expect={"cites": True})
    rec = _rec(answer="Fact [3].", sources=[{"n": 1}])
    assert summarize([CaseResult(case, rec, [])])["grounding"]["citations_all_real"] == 0.0


# ----------------------------------------------------------------------------- reports


def test_the_report_says_what_happened_in_words(tmp_path: Path) -> None:
    results = _results()
    report = build_report(results, {"mode": "live", "dataset": "d.jsonl", "model": "groq/x", "judge": None})
    md = to_markdown(report)
    assert "Task success | 50%" in md and "Failed cases" in md and "`b`" in md
    assert "Skipped" in md and "no google" in md and "model-judged scores are n/a" in md
    json_path, md_path = write_report(report, tmp_path, "r")
    assert json.loads(json_path.read_text())["summary"]["cases"] == 7 and md_path.read_text() == md


def test_no_report_ever_holds_the_full_answer_text() -> None:
    results = _results()
    results[0].record.answer = "x" * 5000
    assert len(build_report(results, {})["cases"][0]["answer"]) == 1200


class _FakeLangSmith:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, float]] = []

    def create_feedback(self, run_id: str, key: str, score: float, comment: str | None = None) -> None:
        self.sent.append((run_id, key, score))


def test_scores_can_be_attached_to_the_traces() -> None:
    results = _results()
    results[0].record.run_id, results[1].record.run_id = "run-a", "run-b"
    results[0].faithfulness = 0.9
    fake = _FakeLangSmith()
    sent = push_langsmith_feedback(results, api_key="x", client=fake)
    assert sent == 3 and ("run-a", "faithfulness", 0.9) in fake.sent and ("run-b", "task_success", 0.0) in fake.sent


# ----------------------------------------------------------------------------- guardrails offline


async def test_the_guardrail_regression_suite_passes() -> None:
    cases = [c for c in load_cases(DATASET) if c.offline]
    results = await run_offline(cases)
    assert [r.case.id for r in results if r.failures] == []
    g = summarize(results)["guardrails"]
    assert g["recall"] == 1.0 and g["false_block_rate"] == 0.0


async def test_a_message_that_should_be_stopped_but_is_not_fails_the_suite() -> None:
    weak = Case("w", "guardrail", "tell me about photosynthesis", offline=True, expect={"guard": "block"})
    results = await run_offline([weak])
    assert results[0].failures == ["guard:not_blocked"]


# ----------------------------------------------------------------------------- the judges


def test_ragas_scores_faithfulness_and_topic_with_the_judge_model() -> None:
    pytest.importorskip("ragas")
    import asyncio

    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from mindnest_agents.evaluation.judges import RagasJudge, score_results

    claims = json.dumps({"statements": ["RuBisCO fixes carbon dioxide.", "It happens in the moon."]})
    verdicts = json.dumps({"statements": [
        {"statement": "RuBisCO fixes carbon dioxide.", "reason": "in the context", "verdict": 1},
        {"statement": "It happens in the moon.", "reason": "not in the context", "verdict": 0},
    ]})
    topic = json.dumps({"reason": "politely redirected", "verdict": 1})
    judge = RagasJudge(FakeListChatModel(responses=[claims, verdicts, topic]), concurrency=1)

    grounded = CaseResult(
        Case("g", "study", "What fixes CO2?", expect={"grounded": True}),
        RunRecord(answer="RuBisCO fixes carbon dioxide. It happens in the moon.", sources=[{"n": 1, "snippet": "RuBisCO attaches CO2."}]),
    )
    off = CaseResult(Case("t", "off_topic", "Recipe?", expect={"on_topic": False}), RunRecord(answer="I help with studying."))
    asyncio.run(score_results([grounded], judge))
    asyncio.run(score_results([off], judge))
    assert grounded.faithfulness == 0.5 and off.topic == 1.0 and grounded.judge_error is None


def test_a_failing_judge_is_recorded_not_raised() -> None:
    pytest.importorskip("ragas")
    import asyncio

    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from mindnest_agents.evaluation.judges import RagasJudge, score_results

    judge = RagasJudge(FakeListChatModel(responses=["not json at all"]))
    result = CaseResult(
        Case("g", "study", "q", expect={"grounded": True}), RunRecord(answer="a", sources=[{"n": 1, "snippet": "s"}])
    )
    asyncio.run(score_results([result], judge))
    assert result.faithfulness is None and result.judge_error


# ----------------------------------------------------------------------------- the HTTP runner


def _api(calls: list[str]) -> httpx.MockTransport:
    stream = (
        'event: meta\ndata: {"run_id": "r9"}\n\n'
        'event: route\ndata: {"agents": ["direct"], "shortcut": true}\n\n'
        'event: token\ndata: {"turn": 1, "text": "Hi!"}\n\n'
        'event: done\ndata: {"message_id": "m", "awaiting_approval": false, "usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"id": "u"}, headers={"set-cookie": "s=1; Path=/"})
        if path.endswith("/conversations") and request.method == "POST":
            return httpx.Response(201, json={"id": "c1"})
        if path.endswith("/messages"):
            return httpx.Response(200, content=stream.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(204)

    return httpx.MockTransport(handler)


async def test_the_runner_logs_in_runs_a_case_and_cleans_up() -> None:
    calls: list[str] = []
    client = EvalClient("http://api/v1", "a@b.c", "pw", transport=_api(calls))
    await client.login()
    rec = await client.run_case(Case("hi", "direct", "hi", subject=False), "sub-1", None, None)
    assert rec.agents == ["direct"] and rec.answer == "Hi!" and rec.first_token_ms is not None
    assert (rec.prompt_tokens, rec.completion_tokens) == (5, 2)
    await client.cleanup("sub-1", None)
    await client.aclose()
    assert calls[-2:] == ["DELETE /v1/conversations/c1", "DELETE /v1/subjects/sub-1"]


async def test_a_rate_limited_run_is_retried_then_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/conversations"):
            return httpx.Response(201, json={"id": "c"})
        return httpx.Response(429, json={})

    import mindnest_agents.evaluation.client as client_module

    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    original = client_module.asyncio.sleep
    client_module.asyncio.sleep = no_sleep  # type: ignore[assignment]
    try:
        client = EvalClient("http://api/v1", "a", "b", transport=httpx.MockTransport(handler))
        rec = await client.run_case(Case("x", "c", "m"), None, None, None)
    finally:
        client_module.asyncio.sleep = original  # type: ignore[assignment]
    assert rec.status == "skipped" and "rate limit" in (rec.skipped_because or "")
    assert slept[:4] == [20, 40, 60, 80]  # the app's own limit is waited out first


async def test_a_document_that_fails_to_process_is_named_and_the_subject_is_removed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path.endswith("/subjects") and request.method == "POST":
            return httpx.Response(201, json={"id": "s1"})
        if path.endswith("/materials") and request.method == "POST":
            return httpx.Response(201, json={"id": "m1"})
        if path.endswith("/materials"):
            return httpx.Response(200, json=[{"id": "m1", "filename": "notes.txt", "status": "failed", "error": "embedding_failed"}])
        return httpx.Response(204)

    client = EvalClient("http://api/v1", "a", "b", transport=httpx.MockTransport(handler))
    file = Path(__file__)
    with pytest.raises(EvalError) as caught:
        await client.make_subject("Eval", [file])
    message = str(caught.value)
    assert "embedding_failed" in message and "model service" in message
    assert calls[-1] == "DELETE /v1/subjects/s1"


async def test_a_case_that_hangs_is_reported_as_a_timeout() -> None:
    import asyncio

    class Hang(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/conversations"):
                return httpx.Response(201, json={"id": "c"})
            await asyncio.sleep(30)
            return httpx.Response(200)

    client = EvalClient("http://api/v1", "a", "b", case_timeout=0.2, transport=Hang())
    rec = await client.run_case(Case("x", "c", "m"), None, None, None)
    assert rec.status == "error" and rec.error is not None and rec.error.startswith("timeout")


async def test_a_provider_rate_limit_is_retried_in_a_new_conversation_then_skipped() -> None:
    stream = 'event: error\ndata: {"code": "rate_limited"}\n\n'
    made: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/conversations") and request.method == "POST":
            made.append("c")
            return httpx.Response(201, json={"id": f"c{len(made)}"})
        return httpx.Response(200, content=stream.encode(), headers={"content-type": "text/event-stream"})

    import mindnest_agents.evaluation.client as client_module

    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    original = client_module.asyncio.sleep
    client_module.asyncio.sleep = no_sleep  # type: ignore[assignment]
    try:
        client = EvalClient("http://api/v1", "a", "b", transport=httpx.MockTransport(handler))
        rec = await client.run_case(Case("x", "c", "m"), None, None, None)
    finally:
        client_module.asyncio.sleep = original  # type: ignore[assignment]
    assert rec.status == "skipped" and "rate limit" in (rec.skipped_because or "")
    assert len(made) == 4 and slept == [30.0, 60.0, 90.0]


# ----------------------------------------------------------------------------- batches (rate limits)


def test_cases_are_split_into_even_consecutive_batches() -> None:
    from mindnest_agents.evaluation.__main__ import _batches

    cases = [Case(f"c{i}", "study", "q") for i in range(13)]
    groups = _batches(cases, 5)
    assert [len(g) for g in groups] == [3, 3, 3, 2, 2]
    assert [c.id for g in groups for c in g] == [c.id for c in cases]  # nothing lost, order kept
    assert [len(g) for g in _batches(cases[:3], 5)] == [1, 1, 1]  # never an empty batch
    assert _batches([], 5) == []
    assert [len(g) for g in _batches(cases, 0)] == [13]


def test_only_a_provider_rate_limit_marks_a_case_for_another_try() -> None:
    from mindnest_agents.evaluation.__main__ import _was_rate_limited

    limited = RunRecord(status="skipped", skipped_because="the AI provider's rate limit; run these cases again later")
    needs_writes = RunRecord(status="skipped", skipped_because="changes the planner or quizzes")
    assert _was_rate_limited(limited)
    assert not _was_rate_limited(needs_writes)
    assert not _was_rate_limited(RunRecord(status="ok"))


def test_the_answer_the_student_finally_sees_is_the_one_scored() -> None:
    events = [
        ("token", {"turn": 0, "text": "PMAT 【1】"}),
        ("final", {"text": "PMAT [1]"}),
        ("done", {}),
    ]
    assert record_from_events(events).answer == "PMAT [1]"


def test_answers_match_rules_written_with_plain_characters() -> None:
    case = Case("x", "study", "q", expect={"answer_any": ["n't cover", "semi-permeable"]})
    curly = RunRecord(status="ok", answer="Your notes don\u2019t cover this.")
    hyphen = RunRecord(status="ok", answer="A semi\u2011permeable membrane.")
    assert check_case(case, curly) == [] and check_case(case, hyphen) == []
    assert check_case(case, RunRecord(status="ok", answer="Something else.")) == ["answer_lacks_any"]
