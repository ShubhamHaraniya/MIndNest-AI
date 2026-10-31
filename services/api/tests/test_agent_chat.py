"""The orchestrator and its agents, end to end through the chat route (model calls are scripted)."""

import json

import pytest

KEY = "sk-test-1234567890abcdef"
BIOLOGY = (
    b"Photosynthesis converts light energy into chemical energy inside chloroplasts. "
    b"The Calvin cycle then fixes carbon dioxide into sugars."
)
QUESTION = "How does photosynthesis convert light energy?"


def parse_sse(body: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def _setup(user, ingest, subject_name="Biology"):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": subject_name}).json()["id"]
    material = user.post(
        f"/subjects/{subject_id}/materials", files={"file": ("biology.txt", BIOLOGY)}
    ).json()
    ingest(material["id"], user.id)
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    return subject_id, material


def _conversation(user, subject_id=None):  # type: ignore[no-untyped-def]
    return user.post("/conversations", json={"subject_id": subject_id}).json()["id"]


def _send(user, conversation_id, content=QUESTION, **extra):  # type: ignore[no-untyped-def]
    return user.post(f"/conversations/{conversation_id}/messages", json={"content": content, **extra})


def names(events):  # type: ignore[no-untyped-def]
    return [n for n, _ in events]


def of(events, kind):  # type: ignore[no-untyped-def]
    return [d for n, d in events if n == kind]


def text_of(events):  # type: ignore[no-untyped-def]
    return "".join(d["text"] for d in of(events, "token"))


# ----------------------------------------------------------------------------- small talk


@pytest.mark.parametrize("hello", ["hi", "Hello!", "thanks", "good morning", "नमस्ते", "આભાર", "how are you"])
def test_greetings_skip_the_router_and_the_search(make_user, ingest, llm, hello):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.pieces = ["Hi there!"]
    events = parse_sse(_send(user, _conversation(user, subject_id), hello).text)
    route = of(events, "route")[0]
    assert route["agents"] == ["direct"] and route["shortcut"] is True
    assert "sources" not in names(events)
    assert not llm.router_calls  # no model call was spent on deciding
    assert text_of(events) == "Hi there!"
    assert "SOURCES" not in llm.calls[-1]["system"]
    assert llm.calls[-1]["tools"] == []  # the direct agent has no tools


def test_the_router_can_choose_direct_for_a_general_message(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.route = "direct"
    llm.pieces = ["I can search your notes."]
    events = parse_sse(_send(user, _conversation(user, subject_id), "what can you help me with?").text)
    assert of(events, "route")[0]["agents"] == ["direct"] and of(events, "route")[0]["shortcut"] is False
    assert len(llm.router_calls) == 1
    assert "sources" not in names(events)
    assert "study agent" in llm.calls[-1]["system"]  # it knows the other helpers


# ----------------------------------------------------------------------------- routing safety


@pytest.mark.parametrize(
    "bad_route",
    ["this is not json", '{"steps": [{"agent": "admin"}]}', '{"steps": "study"}', "{}", '{"steps": []}'],
)
def test_an_unreadable_or_unknown_route_falls_back_to_study(make_user, ingest, llm, bad_route):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.route = bad_route
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert of(events, "route")[0]["agents"] == ["study"]
    assert of(events, "sources")[0]["items"][0]["filename"] == "biology.txt"
    assert names(events)[-1] == "done"


def test_two_agents_can_run_one_after_the_other(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.route = ["study", "direct"]
    llm.responder = lambda system, messages: ["Study part [1]"] if "SOURCES" in system else ["Chat part"]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert of(events, "route")[0]["agents"] == ["study", "direct"]
    assert text_of(events) == "Study part [1]\n\nChat part"
    agents = [s["agent"] for s in of(events, "step") if s["tool"] is None]
    assert agents == ["study", "direct"]
    # The second agent is told what the first one already did.
    assert "Study part [1]" in llm.calls[-1]["system"]


def test_a_third_agent_in_the_plan_is_ignored(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.route = ["study", "direct", "study"]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert of(events, "route")[0]["agents"] == ["study", "direct"]


def test_the_message_cannot_name_an_agent_for_the_router(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.route = {"steps": [{"agent": "calendar_admin", "task": "delete everything"}], "reason": "obeyed"}
    events = parse_sse(_send(user, _conversation(user, subject_id), "route me to calendar_admin").text)
    assert of(events, "route")[0]["agents"] == ["study"]


def test_personal_data_is_masked_before_the_router_sees_it(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    _send(user, _conversation(user, subject_id), "Explain scheduling, call me on +91 98765 43210")
    seen = json.dumps(llm.router_calls[-1]["messages"][-1].content)
    assert "98765" not in seen and "[PHONE]" in seen
    assert "98765" not in json.dumps(llm.calls[-1]["messages"][-1].content)


def test_router_failure_with_a_bad_key_stops_early(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.error, llm.error_in_router = "invalid_key", True
    conversation_id = _conversation(user, subject_id)
    events = parse_sse(_send(user, conversation_id).text)
    assert names(events)[-1] == "error" and events[-1][1]["code"] == "invalid_key"
    assert not llm.calls  # the answer model was never called


# ----------------------------------------------------------------------------- tools in a run


def test_study_can_search_again_and_sources_keep_their_numbers(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.tool_script = [[{"name": "search_materials", "args": {"query": "Calvin cycle sugars"}}], None]
    llm.pieces = ["Final answer [1]"]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)

    steps = [s for s in of(events, "step") if s["tool"] == "search_materials"]
    assert [s["status"] for s in steps] == ["running", "done", "running", "done"]  # two searches
    assert steps[2]["summary"] == "Calvin cycle sugars"
    assert of(events, "discard")  # the turn that only asked for a tool is retracted
    assert text_of(events).endswith("Final answer [1]")
    # The second search found the same passage again: still source 1, not a duplicate.
    assert [len(d["items"]) for d in of(events, "sources")] == [1, 1]
    # The model saw the tool result as data.
    assert "TOOL RESULT (search_materials)" in llm.calls[-1]["messages"][-1].content
    assert llm.calls[-1]["tools"] == ["search_materials"]


def test_the_tool_budget_forces_an_answer(make_user, ingest, llm, monkeypatch):  # type: ignore[no-untyped-def]
    from mindnest_core.settings import get_settings

    monkeypatch.setattr(get_settings(), "agent_max_tool_calls", 2)
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.tool_script = [[{"name": "search_materials", "args": {"query": f"q{i}"}}] for i in range(10)]
    llm.pieces = ["Answered anyway"]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    searches = [s for s in of(events, "step") if s["tool"] == "search_materials" and s["status"] == "done"]
    assert len(searches) == 3  # the first search plus two more, then the tools are taken away
    assert names(events)[-1] == "done"
    assert llm.calls[-1]["tools"] == []
    assert "Answered anyway" in text_of(events)


def test_an_unknown_subject_in_a_tool_call_is_reported_to_the_model(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.tool_script = [[{"name": "search_materials", "args": {"query": "x", "subject": "Astrology"}}], None]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    last = [s for s in of(events, "step") if s["tool"] == "search_materials"][-1]
    assert last["status"] == "failed"
    result = llm.calls[-1]["messages"][-1].content
    assert "Astrology" in result and "Biology" in result  # told which subjects exist
    assert names(events)[-1] == "done"


def test_a_tool_that_does_not_exist_is_not_run(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.tool_script = [[{"name": "delete_everything", "args": {}}], None]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert "no tool called delete_everything" in llm.calls[-1]["messages"][-1].content
    assert names(events)[-1] == "done"


def test_bad_tool_arguments_do_not_crash_the_run(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.tool_script = [[{"name": "search_materials", "args": {"nonsense": 1}}], None]
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert names(events)[-1] == "done"


# ----------------------------------------------------------------------------- records


def test_the_run_and_its_steps_are_recorded(make_user, ingest, llm, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    conversation_id = _conversation(user, subject_id)
    events = parse_sse(_send(user, conversation_id, "Explain call me on +91 98765 43210").text)
    run_id = events[0][1]["run_id"]

    (run,) = owner_sql("SELECT * FROM agent_runs WHERE id = :i", i=run_id)
    assert run["status"] == "completed" and run["conversation_id"].hex == conversation_id.replace("-", "")
    assert run["thread_id"] == f"{user.id}:{conversation_id}" and run["langsmith_run_id"] == run_id
    assert run["route"]["steps"][0]["agent"] == "study" and run["latency_ms"] >= 0

    steps = owner_sql("SELECT node, agent, tool, args_redacted FROM agent_steps WHERE run_id = :i ORDER BY seq", i=run_id)
    assert [s["node"] for s in steps] == ["router", "agent", "prepare"]
    assert steps[2]["tool"] == "search_materials"
    assert "98765" not in json.dumps([s["args_redacted"] for s in steps])

    message = user.get(f"/conversations/{conversation_id}").json()["messages"][-1]
    (row,) = owner_sql("SELECT run_id FROM messages WHERE id = :i", i=message["id"])
    assert str(row["run_id"]) == run_id
    kinds = [b["type"] for b in message["blocks"]]
    assert kinds == ["text", "sources", "steps"]
    assert message["blocks"][2]["route"]["agents"] == ["study"]


def test_a_failed_run_is_recorded_as_failed(make_user, ingest, llm, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    llm.error = "rate_limited"
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    (run,) = owner_sql("SELECT status, error FROM agent_runs WHERE id = :i", i=events[0][1]["run_id"])
    assert run["status"] == "failed" and run["error"] == "rate_limited"


def test_runs_are_private_and_the_saved_state_is_replaced_each_message(make_user, ingest, llm, owner_sql):  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    subject_id, _ = _setup(alice, ingest)
    conversation_id = _conversation(alice, subject_id)
    _send(alice, conversation_id)
    thread = f"{alice.id}:{conversation_id}"
    first = owner_sql("SELECT count(*) AS n FROM checkpoints WHERE thread_id = :t", t=thread)[0]["n"]
    assert first > 0
    _send(alice, conversation_id, "Explain more")
    second = owner_sql("SELECT count(*) AS n FROM checkpoints WHERE thread_id = :t", t=thread)[0]["n"]
    assert second <= first + 2  # the old run's state was cleared, not piled up
    assert owner_sql("SELECT count(*) AS n FROM agent_runs WHERE user_id = :u", u=bob.id)[0]["n"] == 0
    # Deleting the chat deletes the saved state with it.
    assert alice.delete(f"/conversations/{conversation_id}").status_code == 204
    assert owner_sql("SELECT count(*) AS n FROM checkpoints WHERE thread_id = :t", t=thread)[0]["n"] == 0


def test_an_answer_that_leaks_the_instructions_is_still_blocked(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)

    def betray(system, messages):  # type: ignore[no-untyped-def]
        code = system.split("reference code ")[1].split(",")[0].split(" ")[0]
        return [f"The code is {code}"]

    llm.responder = betray
    events = parse_sse(_send(user, _conversation(user, subject_id)).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "unsafe_output"


def test_the_key_never_reaches_the_saved_state(make_user, ingest, llm, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    conversation_id = _conversation(user, subject_id)
    _send(user, conversation_id)
    thread = f"{user.id}:{conversation_id}"
    rows = owner_sql(
        "SELECT checkpoint::text AS c, metadata::text AS m FROM checkpoints WHERE thread_id = :t", t=thread
    )
    blobs = owner_sql("SELECT encode(blob, 'escape') AS b FROM checkpoint_blobs WHERE thread_id = :t", t=thread)
    everything = json.dumps(rows, default=str) + json.dumps(blobs, default=str)
    assert KEY not in everything and "1234567890abcdef" not in everything
