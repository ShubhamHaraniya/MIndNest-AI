"""Quizzes, attempts and spaced revision, with the real worker code and a real database."""

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
MARKER = "marker of a student's short answer"


def sql(query: str, **params: Any) -> list[Any]:
    """Run one statement as the database owner (bypassing row-level security), for set-up and checks."""

    async def go() -> list[Any]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def mine(user, query: str) -> list[Any]:  # type: ignore[no-untyped-def]
    """Rows of one of this student's own table (the query must select FROM a table with user_id)."""
    marker = " FROM "
    head, _, tail = query.partition(marker)
    return sql(f"{head}{marker}{tail} WHERE user_id = :u", u=user.id)


def questions_for(system: str, messages: list[ChatMessage]) -> list[str]:
    """A well-behaved AI: one question per passage, of the type the plan asked for."""
    user = messages[-1].content
    plan = re.findall(r"- Passage (\d+): (\w+)", user)
    items = []
    for number, kind in plan:
        n = int(number)
        base = {"passage": n, "type": kind, "question": f"Question number {n} about the passage?",
                "explanation": f"Because of passage {n}."}
        if kind == "mcq":
            base |= {"options": [f"Right {n}", f"Wrong A{n}", f"Wrong B{n}", f"Wrong C{n}"], "answer": 0}
        elif kind == "true_false":
            base |= {"answer": True}
        else:
            base |= {"answer": f"Model answer {n}"}
        items.append(base)
    return [json.dumps({"questions": items})]


def make_responder(score: float = 1.0, feedback: str = "Well done."):  # type: ignore[no-untyped-def]
    def responder(system: str, messages: list[ChatMessage]) -> list[str]:
        if MARKER in system:
            return [json.dumps({"score": score, "feedback": feedback})]
        return questions_for(system, messages)

    return responder


def setup(user, ingest, llm, responder=None):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": "Biology"}).json()["id"]
    material = user.post(
        f"/subjects/{subject_id}/materials", files={"file": ("notes.txt", NOTES)}
    ).json()
    ingest(material["id"], user.id)
    assert user.get(f"/materials/{material['id']}").json()["status"] == "ready"
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.responder = responder or make_responder()
    return subject_id


def new_quiz(user, subject_id, generate_quiz, queue, **body):  # type: ignore[no-untyped-def]
    payload = {"subject_id": subject_id, "count": 3, "types": ["mcq", "true_false", "short"], **body}
    response = user.post("/quizzes", json=payload)
    assert response.status_code == 201, response.text
    quiz = response.json()
    assert quiz["status"] == "queued"
    assert (quiz["id"], user.id) in queue.quiz_jobs
    generate_quiz(quiz["id"], user.id)
    return user.get(f"/quizzes/{quiz['id']}").json()


def blank_answers(quiz):  # type: ignore[no-untyped-def]
    return [{"question_id": q["id"], "response": ""} for q in quiz["questions"]]


def correct_answers(user, quiz):  # type: ignore[no-untyped-def]
    """Take a throw-away attempt to see the right answers, then answer them properly."""
    first = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    revealed = user.post(f"/attempts/{first['id']}/submit", json={"answers": blank_answers(quiz)}).json()
    return [{"question_id": r["question_id"], "response": r["answer"]} for r in revealed["results"]]


# ------------------------------------------------------------------ making a quiz


def test_a_quiz_is_written_in_the_background_from_the_students_materials(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, count=3, language="hi")
    assert quiz["status"] == "ready" and quiz["question_count"] == len(quiz["questions"]) == 1
    # The tiny test corpus has one passage, so one question; the AI was asked in Hindi.
    assert "Hindi" in llm.calls[-1]["system"]
    assert "chlorophyll" in llm.calls[-1]["messages"][-1].content
    assert llm.calls[-1]["api_key"] == KEY


def test_correct_answers_are_not_sent_before_the_attempt_is_submitted(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    question = quiz["questions"][0]
    assert set(question) == {"id", "position", "qtype", "prompt", "options"}
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    assert user.get(f"/attempts/{attempt['id']}").json()["results"] == []
    # Starting again resumes the same attempt rather than opening a second one.
    assert user.post(f"/quizzes/{quiz['id']}/attempts").json()["id"] == attempt["id"]


def test_creating_a_quiz_needs_a_key_and_processed_materials(make_user, ingest, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = user.post("/subjects", json={"name": "Empty"}).json()["id"]
    body = {"subject_id": subject_id}
    assert user.post("/quizzes", json=body).json()["code"] == "no_provider_key"
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    assert user.post("/quizzes", json=body).json()["code"] == "no_materials"
    assert user.post("/quizzes", json={**body, "count": 2}).status_code == 422
    assert user.post("/quizzes", json={**body, "count": 99}).status_code == 422
    assert user.post("/quizzes", json={**body, "types": ["essay"]}).status_code == 422
    assert user.post("/quizzes", json={**body, "difficulty": "brutal"}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    assert user.post("/quizzes", json={"subject_id": missing}).status_code == 404


def test_a_rejected_key_fails_the_quiz_with_a_clear_reason(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    llm.error = "invalid_key"
    quiz = new_quiz(user, subject_id, generate_quiz, queue)
    assert quiz["status"] == "failed" and quiz["error"] == "invalid_key" and quiz["questions"] == []
    assert user.post(f"/quizzes/{quiz['id']}/attempts").json()["code"] == "quiz_not_ready"


def test_an_ai_that_returns_rubbish_fails_the_quiz_instead_of_showing_it(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm, responder=lambda s, m: ["Sorry, I cannot do that."])
    quiz = new_quiz(user, subject_id, generate_quiz, queue)
    assert quiz["status"] == "failed" and quiz["error"] == "generation_failed"


def test_a_question_of_the_wrong_type_is_dropped(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    def wrong_type(system: str, messages: list[ChatMessage]) -> list[str]:
        (item,) = json.loads(questions_for(system, messages)[0])["questions"]
        item["type"] = "short" if item["type"] != "short" else "mcq"
        return [json.dumps({"questions": [item]})]

    user = make_user()
    subject_id = setup(user, ingest, llm, responder=wrong_type)
    quiz = new_quiz(user, subject_id, generate_quiz, queue)
    assert quiz["status"] == "failed"


def test_questions_come_from_every_material_and_a_short_supply_gives_fewer_questions(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    topics = {
        "history.txt": b"The Battle of Plassey was fought in 1757 between the British East India "
        b"Company and the Nawab of Bengal, and it opened the way for Company rule across eastern India "
        b"during the following decades of the eighteenth century.",
        "civics.txt": b"The Constitution of India came into force on 26 January 1950 after the "
        b"Constituent Assembly had worked on it for almost three years, with Dr B. R. Ambedkar "
        b"chairing the Drafting Committee that wrote the text.",
    }
    for name, data in topics.items():
        material = user.post(f"/subjects/{subject_id}/materials", files={"file": (name, data)}).json()
        ingest(material["id"], user.id)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, count=5, types=["mcq"])
    assert quiz["status"] == "ready" and len(quiz["questions"]) == 3  # only three passages exist
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": []}).json()
    assert {r["source"]["filename"] for r in done["results"]} == {"notes.txt", "history.txt", "civics.txt"}


# ------------------------------------------------------------------ taking a quiz


def test_objective_answers_are_marked_at_once_and_the_right_answers_revealed(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    wrong = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    done = user.post(f"/attempts/{wrong['id']}/submit", json={"answers": blank_answers(quiz)}).json()
    assert done["status"] == "completed" and done["points"] == 0 and done["total"] == 1
    result = done["results"][0]
    assert result["options"][int(result["answer"])] == "Right 1"
    assert result["explanation"] == "Because of passage 1." and result["source"]["filename"] == "notes.txt"

    right = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [{"question_id": result["question_id"], "response": result["answer"]}]
    done = user.post(f"/attempts/{right['id']}/submit", json={"answers": answers}).json()
    assert done["points"] == 1 and done["percent"] == 1.0
    assert user.post(f"/attempts/{right['id']}/submit", json={"answers": answers}).json()["code"] == (
        "already_submitted"
    )
    listed = user.get("/quizzes").json()[0]
    assert listed["attempts"] == 2 and listed["last_attempt"]["percent"] == 1.0


def test_an_answer_for_another_quiz_is_refused(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    stray = {"question_id": "00000000-0000-0000-0000-000000000000", "response": "0"}
    response = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": [stray]})
    assert response.status_code == 422


def test_short_answers_are_marked_by_the_ai_in_the_background(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz, grade_attempt
):
    user = make_user()
    subject_id = setup(user, ingest, llm, responder=make_responder(0.5, "Half right."))
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["short"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [{"question_id": quiz["questions"][0]["id"], "response": "It makes food from light."}]
    submitted = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers}).json()
    assert submitted["status"] == "grading" and submitted["results"][0]["score"] is None
    assert (attempt["id"], user.id) in queue.grade_jobs

    grade_attempt(attempt["id"], user.id)
    done = user.get(f"/attempts/{attempt['id']}").json()
    assert done["status"] == "completed" and done["points"] == 0.5 and done["unscored"] == 0
    assert done["results"][0]["feedback"] == "Half right."
    # What the student typed is sent to the marker as data, with the model answer for comparison.
    sent = llm.calls[-1]["messages"][-1].content
    assert "It makes food from light." in sent and "Model answer 1" in sent


def test_an_empty_short_answer_scores_zero_without_calling_the_ai(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["short"])
    calls_before = len(llm.calls)
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": []}).json()
    assert done["status"] == "completed" and done["points"] == 0 and done["total"] == 1
    assert len(llm.calls) == calls_before


def test_when_the_marker_fails_the_attempt_still_completes_and_says_what_was_not_marked(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz, grade_attempt
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["short"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [{"question_id": quiz["questions"][0]["id"], "response": "Something."}]
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers})
    llm.error = "invalid_key"
    grade_attempt(attempt["id"], user.id)
    done = user.get(f"/attempts/{attempt['id']}").json()
    assert done["status"] == "completed" and done["unscored"] == 1 and done["total"] == 0
    assert done["percent"] is None
    # An unmarked answer must not create or move a revision card.
    assert user.get("/progress").json()["revision"]["cards"] == 0


def test_without_a_key_short_answers_are_left_unmarked_and_the_attempt_still_finishes(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["short"])
    user.request("DELETE", "/settings/providers/openai")
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [{"question_id": quiz["questions"][0]["id"], "response": "Something."}]
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers}).json()
    assert done["status"] == "completed" and done["unscored"] == 1


# ------------------------------------------------------------------ spaced revision


def test_cards_follow_the_leitner_boxes_and_a_revision_quiz_brings_them_back(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    answers = correct_answers(user, quiz)

    # The first (wrong) attempt put the card in box 1, due tomorrow: nothing to revise yet.
    cards = mine(user, "SELECT box, times_seen, times_correct, due_at > now() FROM revision_cards")
    assert cards == [(1, 1, 0, True)]
    assert user.post("/revision/start", json={}).json()["code"] == "nothing_due"
    assert user.get("/progress").json()["revision"]["due"] == 0

    # A right answer moves the card up one box and a week-ish later.
    second = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.post(f"/attempts/{second['id']}/submit", json={"answers": answers})
    cards = mine(user, "SELECT box, times_seen, times_correct, due_at > now() + interval '2 days' FROM revision_cards")
    assert cards == [(2, 2, 1, True)]

    # Time passes: the card is due, and a revision quiz is made from it.
    sql("UPDATE revision_cards SET due_at = now() - interval '1 hour' WHERE user_id = :u", u=user.id)
    overview = user.get("/progress").json()["revision"]
    assert overview["due"] == 1 and overview["boxes"]["2"] == 1
    assert overview["due_by_subject"][0]["name"] == "Biology"
    revision = user.post("/revision/start", json={"count": 5}).json()
    assert revision["source"] == "revision" and revision["status"] == "ready"
    assert revision["question_count"] == 1 and revision["subject_id"] is None
    detail = user.get(f"/quizzes/{revision['id']}").json()
    assert detail["questions"][0]["prompt"] == quiz["questions"][0]["prompt"]

    # Getting it right again goes to box 3; getting it wrong sends it back to box 1.
    take = user.post(f"/quizzes/{revision['id']}/attempts").json()
    # The copied question keeps its answer, so the stored right answer is still right.
    right = [{"question_id": detail["questions"][0]["id"], "response": answers[0]["response"]}]
    user.post(f"/attempts/{take['id']}/submit", json={"answers": right})
    assert mine(user, "SELECT box, times_seen FROM revision_cards") == [(3, 3)]
    sql("UPDATE revision_cards SET due_at = now() - interval '1 hour' WHERE user_id = :u", u=user.id)
    again = user.post("/revision/start", json={}).json()
    miss = user.post(f"/quizzes/{again['id']}/attempts").json()
    detail = user.get(f"/quizzes/{again['id']}").json()
    user.post(f"/attempts/{miss['id']}/submit", json={"answers": blank_answers(detail)})
    assert mine(user, "SELECT box, times_seen FROM revision_cards") == [(1, 4)]
    assert mine(user, "SELECT count(*) FROM revision_cards") == [(1,)]  # still one card for the one question


def test_deleting_a_quiz_keeps_the_cards_the_student_still_has_to_revise(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": blank_answers(quiz)})
    assert user.delete(f"/quizzes/{quiz['id']}").status_code == 204
    assert user.get(f"/quizzes/{quiz['id']}").status_code == 404
    assert user.get(f"/attempts/{attempt['id']}").status_code == 404
    assert mine(user, "SELECT count(*) FROM revision_cards") == [(1,)]
    assert user.get("/progress").json()["revision"]["cards"] == 1


def test_progress_summarises_attempts_per_subject(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    empty = user.get("/progress").json()
    assert empty["attempts"] == 0 and empty["average"] is None and empty["recent"] == []
    subject_id = setup(user, ingest, llm)
    quiz = new_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    answers = correct_answers(user, quiz)  # first attempt scores 0
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers})  # second scores 1
    progress = user.get("/progress").json()
    assert progress["attempts"] == 2 and progress["average"] == 0.5
    assert progress["subjects"][0]["name"] == "Biology" and progress["subjects"][0]["average"] == 0.5
    assert progress["recent"][0]["percent"] == 1.0
    assert len(user.get(f"/quizzes/{quiz['id']}/attempts").json()) == 2


# ------------------------------------------------------------------ privacy


def test_quizzes_attempts_and_cards_are_private(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    owner, other = make_user(), make_user()
    subject_id = setup(owner, ingest, llm)
    quiz = new_quiz(owner, subject_id, generate_quiz, queue, types=["mcq"])
    attempt = owner.post(f"/quizzes/{quiz['id']}/attempts").json()
    owner.post(f"/attempts/{attempt['id']}/submit", json={"answers": blank_answers(quiz)})
    sql("UPDATE revision_cards SET due_at = now() - interval '1 hour' WHERE user_id = :u", u=owner.id)

    assert other.get("/quizzes").json() == []
    assert other.get(f"/quizzes/{quiz['id']}").status_code == 404
    assert other.delete(f"/quizzes/{quiz['id']}").status_code == 404
    assert other.post(f"/quizzes/{quiz['id']}/attempts").status_code == 404
    assert other.get(f"/attempts/{attempt['id']}").status_code == 404
    assert other.get(f"/quizzes/{quiz['id']}/attempts").status_code == 404
    assert other.post(f"/attempts/{attempt['id']}/submit", json={"answers": []}).status_code == 404
    assert other.post("/revision/start", json={}).json()["code"] == "nothing_due"
    progress = other.get("/progress").json()
    assert progress["attempts"] == 0 and progress["revision"] == {
        "cards": 0, "due": 0, "next_due_at": None,
        "boxes": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}, "due_by_subject": [],
    }
    # Another student's subject cannot be used to make a quiz either.
    other.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    assert other.post("/quizzes", json={"subject_id": subject_id}).status_code == 404


def test_quiz_routes_need_a_signed_in_student(anon):  # type: ignore[no-untyped-def]
    for method, path in (
        ("GET", "/quizzes"), ("POST", "/quizzes"), ("GET", "/progress"), ("POST", "/revision/start"),
        ("GET", "/attempts/00000000-0000-0000-0000-000000000000"),
    ):
        assert anon.request(method, path, json={}).status_code == 401, path
