import json

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


def _subject(user, name="Biology"):  # type: ignore[no-untyped-def]
    return user.post("/subjects", json={"name": name}).json()["id"]


def _add_material(user, ingest, subject_id, name="biology.txt", data=BIOLOGY):  # type: ignore[no-untyped-def]
    material = user.post(f"/subjects/{subject_id}/materials", files={"file": (name, data)}).json()
    ingest(material["id"], user.id)
    return material


def _setup(user, ingest, subject_name="Biology"):  # type: ignore[no-untyped-def]
    subject_id = _subject(user, subject_name)
    material = _add_material(user, ingest, subject_id)
    assert user.get(f"/materials/{material['id']}").json()["status"] == "ready"
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    return subject_id, material


def _conversation(user, subject_id=None):  # type: ignore[no-untyped-def]
    response = user.post("/conversations", json={"subject_id": subject_id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _send(user, conversation_id, content=QUESTION, **extra):  # type: ignore[no-untyped-def]
    return user.post(
        f"/conversations/{conversation_id}/messages", json={"content": content, **extra}
    )


def test_answer_streams_with_sources_and_is_saved(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, material = _setup(user, ingest)
    conversation_id = _conversation(user, subject_id)

    response = _send(user, conversation_id)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in response.headers["cache-control"]
    events = parse_sse(response.text)
    assert [name for name, _ in events if name != "step"] == [
        "meta", "route", "sources", "token", "token", "done",
    ]
    meta, sources = events[0][1], dict(events)["sources"]
    assert meta["provider"] == "openai" and meta["title"] == QUESTION
    assert sources["items"][0]["filename"] == "biology.txt"
    assert sources["items"][0]["material_id"] == material["id"]
    assert sources["items"][0]["n"] == 1
    assert "".join(data["text"] for name, data in events if name == "token") == "Hello world [1]"

    # The model saw the student's passage as a numbered source, and the student's own key.
    call = llm.calls[-1]
    assert call["api_key"] == KEY
    assert '<source id="1" file="biology.txt"' in call["system"]
    assert "Calvin cycle" in call["system"]
    assert call["messages"][-1].content == QUESTION

    detail = user.get(f"/conversations/{conversation_id}").json()
    assert detail["title"] == QUESTION
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    answer = detail["messages"][1]["blocks"]
    assert answer[0] == {"type": "text", "text": "Hello world [1]"}
    assert answer[1]["type"] == "sources" and answer[1]["items"][0]["filename"] == "biology.txt"


def test_follow_up_sends_earlier_turns_to_the_model(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = _setup(user, ingest)
    conversation_id = _conversation(user, subject_id)
    _send(user, conversation_id)
    _send(user, conversation_id, "Explain more")
    roles = [m.role for m in llm.calls[-1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert llm.calls[-1]["messages"][1].content == "Hello world [1]"


def test_search_is_limited_to_the_chosen_subject(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    _setup(user, ingest, "Biology")
    history = _subject(user, "History")
    other = _conversation(user, history)
    events = parse_sse(_send(user, other).text)
    assert dict(events)["sources"]["items"] == []
    assert "SOURCES: none" in llm.calls[-1]["system"]

    everywhere = _conversation(user, None)
    events = parse_sse(_send(user, everywhere).text)
    assert dict(events)["sources"]["items"][0]["filename"] == "biology.txt"


def test_other_students_materials_are_never_searched(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    _setup(alice, ingest)
    bob.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    events = parse_sse(_send(bob, _conversation(bob)).text)
    assert dict(events)["sources"]["items"] == []
    assert "Calvin cycle" not in llm.calls[-1]["system"]


def test_a_key_is_required(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    response = _send(user, _conversation(user))
    assert response.status_code == 409 and response.json()["code"] == "no_provider_key"
    user.request("PUT", "/settings/providers/groq", json={"api_key": KEY})
    pinned = _send(user, _conversation(user), provider="openai")
    assert pinned.status_code == 409


def test_provider_and_model_choice_is_remembered(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/groq", json={"api_key": KEY, "model": "llama-3.1-8b-instant"})
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    conversation_id = _conversation(user)
    _send(user, conversation_id, provider="groq", model="llama-3.3-70b-versatile")
    assert llm.calls[-1]["provider"] == "groq"
    assert llm.calls[-1]["model"] == "llama-3.3-70b-versatile"
    _send(user, conversation_id, "again")  # no choice sent: the conversation's provider is used
    assert llm.calls[-1]["provider"] == "groq"
    assert user.get(f"/conversations/{conversation_id}").json()["model"] == "llama-3.3-70b-versatile"
    assert _send(user, conversation_id, "x", model="bad model!").status_code == 422


def test_provider_failure_before_any_text_is_reported_and_nothing_is_saved(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.error = "invalid_key"
    conversation_id = _conversation(user)
    events = parse_sse(_send(user, conversation_id).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "invalid_key"
    roles = [m["role"] for m in user.get(f"/conversations/{conversation_id}").json()["messages"]]
    assert roles == ["user"]


def test_partial_answer_is_kept_when_the_provider_fails_midway(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.pieces = ["Part one ", "part two"]
    llm.error, llm.fail_after = "provider_unavailable", 1
    conversation_id = _conversation(user)
    events = parse_sse(_send(user, conversation_id).text)
    assert [n for n, _ in events][-2:] == ["token", "error"]
    blocks = user.get(f"/conversations/{conversation_id}").json()["messages"][-1]["blocks"]
    assert blocks[0]["text"] == "Part one "
    assert {"type": "error", "code": "provider_unavailable"} in blocks


def test_conversations_are_private_and_manageable(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    alice.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    conversation_id = _conversation(alice)
    assert [c["id"] for c in alice.get("/conversations").json()] == [conversation_id]
    assert bob.get("/conversations").json() == []
    assert bob.get(f"/conversations/{conversation_id}").status_code == 404
    assert _send(bob, conversation_id).status_code == 404
    assert bob.delete(f"/conversations/{conversation_id}").status_code == 404
    assert bob.post("/conversations", json={"subject_id": _subject(alice)}).status_code == 404

    renamed = alice.patch(f"/conversations/{conversation_id}", json={"title": "Exam prep"})
    assert renamed.json()["title"] == "Exam prep"
    assert alice.patch(f"/conversations/{conversation_id}", json={"title": "  "}).status_code == 422
    assert alice.delete(f"/conversations/{conversation_id}").status_code == 204
    assert alice.get(f"/conversations/{conversation_id}").status_code == 404


def test_empty_and_oversized_messages_are_rejected(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    conversation_id = _conversation(user)
    assert _send(user, conversation_id, "   ").status_code == 422
    assert _send(user, conversation_id, "x" * 8001).status_code == 422
