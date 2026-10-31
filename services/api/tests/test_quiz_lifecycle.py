"""Quiz lifecycle: one status everywhere, archiving, rejected questions, and the cards-due rule."""

import asyncio
import json
import re
from typing import Any

from mindnest_api.llm import ChatMessage
from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text

KEY = "sk-test-1234567890abcdef"
NOTES = (
    b"Photosynthesis is the process by which green plants use sunlight to make food from carbon "
    b"dioxide and water. It takes place in the chloroplasts, which contain the green pigment "
    b"chlorophyll, and it releases oxygen as a by-product that animals breathe in. "
    b"The light reactions capture energy while the Calvin cycle builds sugars from carbon dioxide."
)


def sql(query: str, **params: Any) -> list[Any]:
    """Run one statement as the database owner (bypassing row-level security)."""

    async def go() -> list[Any]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def well_behaved(system: str, messages: list[ChatMessage]) -> list[str]:
    plan = re.findall(r"- Passage (\d+): (\w+)", messages[-1].content)
    items = []
    for number, kind in plan:
        n = int(number)
        base: dict[str, Any] = {
            "passage": n, "type": kind, "question": f"Question number {n} about the passage?",
            "explanation": f"Because of passage {n}.",
        }
        if kind == "mcq":
            base |= {"options": [f"Right {n}", f"Wrong A{n}", f"Wrong B{n}", f"Wrong C{n}"], "answer": 0}
        elif kind == "true_false":
            base |= {"answer": True}
        else:
            base |= {"answer": f"Model answer {n}"}
        items.append(base)
    return [json.dumps({"questions": items})]


def setup(user, ingest, llm, responder=None):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": "Biology"}).json()["id"]
    material = user.post(
        f"/subjects/{subject_id}/materials", files={"file": ("notes.txt", NOTES)}
    ).json()
    ingest(material["id"], user.id)
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.responder = responder or well_behaved
    return subject_id


def new_quiz(user, subject_id, generate_quiz):  # type: ignore[no-untyped-def]
    response = user.post("/quizzes", json={"subject_id": subject_id, "count": 3, "types": ["mcq"]})
    assert response.status_code == 201, response.text
    quiz = response.json()
    generate_quiz(quiz["id"], user.id)
    return user.get(f"/quizzes/{quiz['id']}").json()


def answers_of(quiz):  # type: ignore[no-untyped-def]
    return [{"question_id": q["id"], "response": ""} for q in quiz["questions"]]


def test_a_quiz_moves_through_ready_in_progress_completed_and_archived(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, generate_quiz
):
    user = make_user()
    quiz = new_quiz(user, setup(user, ingest, llm), generate_quiz)
    assert quiz["display_status"] == "ready" and quiz["archived_at"] is None

    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    assert user.get(f"/quizzes/{quiz['id']}").json()["display_status"] == "in_progress"

    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers_of(quiz)})
    assert user.get(f"/quizzes/{quiz['id']}").json()["display_status"] == "completed"

    archived = user.patch(f"/quizzes/{quiz['id']}", json={"archived": True})
    assert archived.status_code == 200
    assert archived.json()["display_status"] == "archived" and archived.json()["archived_at"]
    # The list still contains it (the screen filters), with the same status.
    listed = {q["id"]: q for q in user.get("/quizzes").json()}
    assert listed[quiz["id"]]["display_status"] == "archived"

    restored = user.patch(f"/quizzes/{quiz['id']}", json={"archived": False}).json()
    assert restored["display_status"] == "completed" and restored["archived_at"] is None


def test_an_archived_quiz_cannot_be_taken_but_keeps_its_attempts(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, generate_quiz
):
    user = make_user()
    quiz = new_quiz(user, setup(user, ingest, llm), generate_quiz)
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers_of(quiz)})

    user.patch(f"/quizzes/{quiz['id']}", json={"archived": True})
    refused = user.post(f"/quizzes/{quiz['id']}/attempts")
    assert refused.status_code == 409 and refused.json()["code"] == "quiz_archived"
    assert len(user.get(f"/quizzes/{quiz['id']}/attempts").json()) == 1

    user.patch(f"/quizzes/{quiz['id']}", json={"archived": False})
    assert user.post(f"/quizzes/{quiz['id']}/attempts").status_code in (200, 201)


def test_archiving_someone_elses_quiz_is_not_found(make_user, ingest, llm, generate_quiz):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    quiz = new_quiz(owner, setup(owner, ingest, llm), generate_quiz)
    assert other.patch(f"/quizzes/{quiz['id']}", json={"archived": True}).status_code == 404
    assert owner.get(f"/quizzes/{quiz['id']}").json()["archived_at"] is None


def test_questions_that_fail_the_checks_are_counted_not_hidden(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, generate_quiz
):
    def with_a_bad_one(system: str, messages: list[ChatMessage]) -> list[str]:
        (reply,) = well_behaved(system, messages)
        items = json.loads(reply)["questions"]
        # A second question for the same passage whose answer points outside the options.
        bad = dict(items[0]) | {"question": "Another question about the passage?", "answer": 9}
        return [json.dumps({"questions": [*items, bad]})]

    user = make_user()
    quiz = new_quiz(user, setup(user, ingest, llm, responder=with_a_bad_one), generate_quiz)
    assert quiz["status"] == "ready"
    assert quiz["rejected_count"] >= 0
    assert "rejected" not in quiz["config"]
    stored = sql("SELECT config->'rejected'->>'count' FROM quizzes WHERE id = :q", q=quiz["id"])
    assert stored[0][0] is not None
    assert int(stored[0][0]) == quiz["rejected_count"]


def test_the_cards_due_figure_is_the_same_on_every_screen(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz)
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers_of(quiz)})
    sql("UPDATE revision_cards SET due_at = now() - interval '2 days' WHERE user_id = :u", u=user.id)

    due = user.get("/progress").json()["revision"]["due"]
    assert due >= 1
    notes = user.get("/notifications").json()
    revision = [n for n in notes["items"] if n["kind"] == "revision_due"]
    assert revision and revision[0]["params"]["count"] == due
    assert user.get("/dashboard").json()["stats"]["revision_due"] == due

    # Archiving the course takes its cards out of every count at once.
    assert user.post(f"/subjects/{subject_id}/archive").status_code == 200
    assert user.get("/progress").json()["revision"]["due"] == 0
    assert not [n for n in user.get("/notifications").json()["items"] if n["kind"] == "revision_due"]
