"""The Calendar agent in chat: reading is free, every change pauses for the student's approval.

Runs through the real chat routes, the real graph (with its saved checkpoints), the real calendar
server over HTTP and a fake Google."""

import json
from datetime import UTC, datetime, timedelta

from mindnest_core.calevent import EventIn, google_body

KEY = "sk-test-1234567890abcdef"


def parse_sse(body: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def of(events, kind):  # type: ignore[no-untyped-def]
    return [d for n, d in events if n == kind]


def day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def ready(user, link_google, llm, calendar_api, *, connected=True):  # type: ignore[no-untyped-def]
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    if connected:
        link_google(user)
    llm.route = "calendar"
    llm.pieces = ["All done."]


def chat(user, content, conversation=None):  # type: ignore[no-untyped-def]
    conversation = conversation or user.post("/conversations", json={}).json()["id"]
    response = user.post(f"/conversations/{conversation}/messages", json={"content": content})
    assert response.status_code == 200, response.text
    return conversation, parse_sse(response.text)


def decide(user, conversation, run_id, decision, edits=None):  # type: ignore[no-untyped-def]
    body = {"decision": decision, **({"edits": edits} if edits else {})}
    return user.post(f"/conversations/{conversation}/runs/{run_id}/decision", json=body)


def proposal_of(events):  # type: ignore[no-untyped-def]
    found = [c for c in of(events, "card") if c["kind"] == "calendar_proposal"]
    assert len(found) == 1, events
    return found[0]["data"]


def last_message(user, conversation):  # type: ignore[no-untyped-def]
    return user.get(f"/conversations/{conversation}").json()["messages"][-1]


def card_blocks(message, kind="calendar_proposal"):  # type: ignore[no-untyped-def]
    return [b["data"] for b in message["blocks"] if b["type"] == "card" and b["kind"] == kind]


def add_args(**over):  # type: ignore[no-untyped-def]
    return {"summary": "Revise cells", "day": day(3), "start_time": "18:30", "minutes": 45, **over}


def run_status(owner_sql, run_id):  # type: ignore[no-untyped-def]
    return owner_sql("SELECT status FROM agent_runs WHERE id = :r", r=run_id)[0]["status"]


# ------------------------------------------------------------------ add


def test_adding_an_event_pauses_for_approval_and_changes_nothing_until_then(make_user, link_google, llm, calendar_api, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Put a study session on my calendar")

    card = proposal_of(events)
    assert card["status"] == "pending" and card["action"] == "add" and card["editable"] is True
    assert card["event"]["summary"] == "Revise cells" and card["event"]["start_time"] == "18:30"
    assert of(events, "done")[0]["awaiting_approval"] is True
    assert calendar_api.events == {} and not any(c[0] == "insert" for c in calendar_api.calls)
    steps = [s for s in of(events, "step") if s["tool"] == "add_event"]
    assert [s["status"] for s in steps][-1] == "waiting"  # shown as waiting for the student
    assert run_status(owner_sql, card["run_id"]) == "interrupted"
    # Seen again after a reload, the card is still waiting.
    assert card_blocks(last_message(user, conversation))[0]["status"] == "pending"


def test_approving_adds_a_real_event_with_a_link_and_finishes_the_answer(make_user, link_google, llm, calendar_api, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Put a study session on my calendar")
    card = proposal_of(events)

    response = decide(user, conversation, card["run_id"], "approve")
    assert response.status_code == 200, response.text
    after = parse_sse(response.text)
    settled = of(after, "card_update")[0]
    assert settled["status"] == "approved" and settled["result"]["link"].startswith("https://calendar.google.com/")
    assert of(after, "done")[0]["awaiting_approval"] is False
    (event,) = calendar_api.events.values()
    assert event["summary"] == "Revise cells" and event["start"]["dateTime"].endswith("18:30:00")
    assert event["end"]["dateTime"].endswith("19:15:00")

    message = last_message(user, conversation)
    (saved,) = card_blocks(message)
    assert saved["status"] == "approved" and saved["result"]["link"] == settled["result"]["link"]
    assert any(b["type"] == "text" and "All done." in b["text"] for b in message["blocks"])
    assert run_status(owner_sql, card["run_id"]) == "completed"
    assert len(user.get(f"/conversations/{conversation}").json()["messages"]) == 2  # one answer, not two


def test_the_student_can_edit_before_approving(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Add a study session")
    card = proposal_of(events)
    response = decide(user, conversation, card["run_id"], "approve",
                      {"summary": "Revise cells properly", "start_time": "19:00", "minutes": 90, "day": day(4)})
    assert response.status_code == 200, response.text
    (event,) = calendar_api.events.values()
    assert event["summary"] == "Revise cells properly" and event["start"]["dateTime"] == f"{day(4)}T19:00:00"
    assert event["end"]["dateTime"] == f"{day(4)}T20:30:00"
    (saved,) = card_blocks(last_message(user, conversation))
    assert saved["event"]["summary"] == "Revise cells properly"


def test_an_all_day_event_has_no_time(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": {"summary": "Fee due", "day": day(5)}}]]
    conversation, events = chat(user, "Remind me about the fee")
    assert proposal_of(events)["event"]["all_day"] is True
    decide(user, conversation, proposal_of(events)["run_id"], "approve")
    (event,) = calendar_api.events.values()
    assert event["start"] == {"date": day(5)} and event["end"] == {"date": day(6)}


def test_declining_adds_nothing(make_user, link_google, llm, calendar_api, owner_sql):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Put a study session on my calendar")
    card = proposal_of(events)
    after = parse_sse(decide(user, conversation, card["run_id"], "reject").text)
    assert of(after, "card_update")[0]["status"] == "rejected"
    assert calendar_api.events == {}
    assert "NOTHING" in llm.calls[-1]["messages"][-1].content  # the model was told it was declined
    assert card_blocks(last_message(user, conversation))[0]["status"] == "rejected"
    assert run_status(owner_sql, card["run_id"]) == "completed"


def test_a_proposal_can_be_answered_only_once(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Add it")
    run_id = proposal_of(events)["run_id"]
    assert decide(user, conversation, run_id, "approve").status_code == 200
    again = decide(user, conversation, run_id, "approve")
    assert again.status_code == 409 and again.json()["code"] == "approval_expired"
    assert len(calendar_api.events) == 1


def test_a_newer_message_makes_the_old_proposal_expire(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Add it")
    run_id = proposal_of(events)["run_id"]
    llm.route = "direct"
    chat(user, "never mind, thanks", conversation)
    late = decide(user, conversation, run_id, "approve")
    assert late.status_code == 409 and late.json()["code"] == "approval_expired"
    assert calendar_api.events == {}
    first = user.get(f"/conversations/{conversation}").json()["messages"][1]
    assert card_blocks(first)[0]["status"] == "expired"


def test_somebody_elses_proposal_cannot_be_answered(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    ready(owner, link_google, llm, calendar_api)
    other.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(owner, "Add it")
    response = decide(other, conversation, proposal_of(events)["run_id"], "approve")
    assert response.status_code == 404
    assert calendar_api.events == {}


def test_bad_edits_are_refused_before_anything_runs(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Add it")
    run_id = proposal_of(events)["run_id"]
    for edits in ({"start_time": "25:99"}, {"minutes": 1}, {"summary": ""}, {"nonsense": 1}):
        assert decide(user, conversation, run_id, "approve", edits).status_code == 422, edits
    assert decide(user, conversation, run_id, "approve").status_code == 200  # still waiting, still answerable


def test_a_past_date_is_not_proposed(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args(day=day(-3))}]]
    _, events = chat(user, "Add it")
    assert not [c for c in of(events, "card") if c["kind"] == "calendar_proposal"]
    assert of(events, "done")[0]["awaiting_approval"] is False
    assert "in the past" in llm.calls[-1]["messages"][-1].content


def test_google_failing_after_approval_is_reported_not_hidden(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    conversation, events = chat(user, "Add it")
    calendar_api.fail["insert"] = 500
    after = parse_sse(decide(user, conversation, proposal_of(events)["run_id"], "approve").text)
    assert of(after, "card_update")[0]["status"] == "failed" and of(after, "card_update")[0]["error"] == "google_500"
    assert calendar_api.events == {}
    assert "ERROR" in llm.calls[-1]["messages"][-1].content
    assert card_blocks(last_message(user, conversation))[0]["status"] == "failed"


def test_without_google_connected_nothing_is_proposed_and_a_connect_card_is_shown(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api, connected=False)
    llm.tool_script = [[{"name": "add_event", "args": add_args()}]]
    _, events = chat(user, "Add it")
    assert [c["data"]["reason"] for c in of(events, "card") if c["kind"] == "calendar_connect"] == ["not_connected"]
    assert not [c for c in of(events, "card") if c["kind"] == "calendar_proposal"]
    assert calendar_api.calls == []


def test_a_change_is_asked_for_on_its_own(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "list_events", "args": {}}, {"name": "add_event", "args": add_args()}]]
    _, events = chat(user, "Show my calendar and add a session")
    assert proposal_of(events)["action"] == "add"
    assert not any(c[0] == "list" for c in calendar_api.calls)  # the read in the same round was not run


def test_two_changes_in_a_row_need_two_approvals(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [
        [{"name": "add_event", "args": add_args(summary="One")}],
        [{"name": "add_event", "args": add_args(summary="Two", day=day(4))}],
    ]
    conversation, events = chat(user, "Add two sessions")
    first = proposal_of(events)
    second_events = parse_sse(decide(user, conversation, first["run_id"], "approve").text)
    second = [c for c in of(second_events, "card") if c["kind"] == "calendar_proposal"][0]["data"]
    assert second["event"]["summary"] == "Two" and of(second_events, "done")[0]["awaiting_approval"] is True
    assert len(calendar_api.events) == 1
    decide(user, conversation, first["run_id"], "approve")
    assert sorted(e["summary"] for e in calendar_api.events.values()) == ["One", "Two"]
    statuses = [b["status"] for b in card_blocks(last_message(user, conversation))]
    assert statuses == ["approved", "approved"]


# ------------------------------------------------------------------ read


def test_listing_shows_a_card_and_needs_no_approval(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    calendar_api.events["evA"] = google_body(EventIn(summary="Chem lab", day=datetime.now(UTC).date() + timedelta(days=1),
                                                       start_time="10:00", minutes=120))
    llm.tool_script = [[{"name": "list_events", "args": {}}]]
    _, events = chat(user, "What is on my calendar this week?")
    (card,) = [c for c in of(events, "card") if c["kind"] == "calendar_events"]
    assert [e["summary"] for e in card["data"]["events"]] == ["Chem lab"]
    assert of(events, "done")[0]["awaiting_approval"] is False
    assert "evA" in llm.calls[-1]["messages"][-1].content


# ------------------------------------------------------------------ move and remove


def seed(calendar_api, summary="Chem lab", offset=2, start="10:00"):  # type: ignore[no-untyped-def]
    calendar_api.events["evA"] = google_body(
        EventIn(summary=summary, day=datetime.now(UTC).date() + timedelta(days=offset), start_time=start,
                minutes=60, timezone="UTC", transparent=True, source_type="task", source_id="abc")
    )


def test_moving_shows_before_and_after_and_keeps_the_rest(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    seed(calendar_api)
    llm.tool_script = [[{"name": "move_event", "args": {"event_id": "evA", "day": day(5), "start_time": "14:00"}}]]
    conversation, events = chat(user, "Move my chem lab to day after")
    card = proposal_of(events)
    assert card["action"] == "move" and card["before"]["start_time"] == "10:00" and card["event"]["start_time"] == "14:00"
    assert calendar_api.events["evA"]["start"]["dateTime"].endswith("10:00:00")  # untouched so far
    decide(user, conversation, card["run_id"], "approve")
    moved = calendar_api.events["evA"]
    assert moved["start"]["dateTime"] == f"{day(5)}T14:00:00" and moved["summary"] == "Chem lab"
    assert moved["transparency"] == "transparent"
    assert moved["extendedProperties"]["private"]["source"] == "task"
    assert len(calendar_api.events) == 1


def test_removing_needs_approval_and_then_deletes(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    seed(calendar_api)
    llm.tool_script = [[{"name": "remove_event", "args": {"event_id": "evA"}}]]
    conversation, events = chat(user, "Cancel my chem lab")
    card = proposal_of(events)
    assert card["action"] == "remove" and card["editable"] is False and card["event"]["summary"] == "Chem lab"
    assert "evA" in calendar_api.events
    decide(user, conversation, card["run_id"], "approve")
    assert calendar_api.events == {}


def test_an_event_that_is_not_there_is_not_proposed(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "remove_event", "args": {"event_id": "ghost"}}]]
    _, events = chat(user, "Cancel it")
    assert not [c for c in of(events, "card") if c["kind"] == "calendar_proposal"]
    assert "no longer on the calendar" in llm.calls[-1]["messages"][-1].content


def test_the_agent_is_in_the_routers_list(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.route = "direct"
    chat(user, "What can you do with my calendar?")
    assert '"calendar"' in llm.router_calls[-1]["system"]


def test_router_prompt_sends_timed_sessions_to_calendar() -> None:
    from mindnest_api.agent.router import ROUTER_SYSTEM

    assert "specific clock time" in ROUTER_SYSTEM
    assert "never a clock time" in ROUTER_SYSTEM


# ------------------------------------------------------------------ guardrails and the calendar


def test_a_proposal_with_a_link_the_student_never_wrote_is_stopped_before_it_is_even_shown(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    llm.tool_script = [[{"name": "add_event", "args": add_args(description="details at https://evil.example/?q=1")}], None]
    llm.pieces = ["I did not add it."]
    _conversation, events = chat(user, "Put a study session on my calendar")
    assert of(events, "card") == [] or all(c["kind"] != "calendar_proposal" for c in of(events, "card"))
    guard = [s for s in of(events, "step") if s["agent"] == "guardrails"]
    assert guard and guard[0]["tool"] == "tool_call" and guard[0]["status"] == "blocked"
    assert calendar_api.events == {}


def test_a_link_the_student_typed_survives_the_pause_and_the_resume(make_user, link_google, llm, calendar_api):  # type: ignore[no-untyped-def]
    user = make_user()
    ready(user, link_google, llm, calendar_api)
    link = "https://meet.example.com/abc-def"
    llm.tool_script = [[{"name": "add_event", "args": add_args(description=link)}]]
    conversation, events = chat(user, f"Put a study session on my calendar, meeting link {link}")
    card = proposal_of(events)  # not stopped: the student wrote the link
    resumed = parse_sse(decide(user, conversation, card["run_id"], "approve").text)
    assert not of(resumed, "error")
    assert any(e["description"] == link for e in calendar_api.events.values())
