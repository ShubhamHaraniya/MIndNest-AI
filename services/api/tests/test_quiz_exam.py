"""The exam side of quizzes: time limits, autosave, the analytical result and the follow-ups.

Grading itself is covered in test_quizzes.py; here it must simply stay the same.
"""

import asyncio
import json
import re
import uuid
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
MISSING = "00000000-0000-0000-0000-000000000000"


def sql(query: str, **params: Any) -> list[Any]:
    """One statement as the database owner (bypassing row-level security), for set-up and checks."""

    async def go() -> list[Any]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def respond(system: str, messages: list[ChatMessage]) -> list[str]:
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


def setup(user, ingest, llm) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """A subject with one processed material and an AI key; returns (subject id, material id)."""
    subject_id = user.post("/subjects", json={"name": "Biology"}).json()["id"]
    material = user.post(f"/subjects/{subject_id}/materials", files={"file": ("notes.txt", NOTES)}).json()
    ingest(material["id"], user.id)
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.responder = respond
    return subject_id, material["id"]


def make_quiz(user, subject_id, generate_quiz, queue, **body):  # type: ignore[no-untyped-def]
    payload = {"subject_id": subject_id, "count": 3, "types": ["mcq"], **body}
    response = user.post("/quizzes", json=payload)
    assert response.status_code == 201, response.text
    quiz = response.json()
    generate_quiz(quiz["id"], user.id)
    return user.get(f"/quizzes/{quiz['id']}").json()


def seeded_quiz(user, subject_id, title, sources, ready=True):  # type: ignore[no-untyped-def]
    """A ready quiz of true/false questions (marked at once), one per source file name."""
    quiz_id = str(uuid.uuid4())
    sql(
        "INSERT INTO quizzes (id, user_id, subject_id, title, status, question_count) "
        "VALUES (:q, :u, :s, :t, 'ready', :n)",
        q=quiz_id, u=user.id, s=subject_id, t=title, n=len(sources),
    )
    for position, filename in enumerate(sources, start=1):
        source = None if filename is None else json.dumps({"filename": filename, "text": "x"})
        sql(
            "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, answer, source) "
            "VALUES (:q, :u, :p, 'true_false', :pr, 'true', CAST(:src AS jsonb))",
            q=quiz_id, u=user.id, p=position, pr=f"Statement {position}", src=source,
        )
    return user.get(f"/quizzes/{quiz_id}").json()


def answer_all(user, quiz, correct_count):  # type: ignore[no-untyped-def]
    """Take an attempt answering the first `correct_count` true/false questions rightly."""
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [
        {"question_id": q["id"], "response": "true" if i < correct_count else "false"}
        for i, q in enumerate(quiz["questions"])
    ]
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers})
    assert done.status_code == 200, done.text
    return done.json()


# ------------------------------------------------------------------ the exam session


def test_a_session_gives_the_exam_screen_everything_and_the_server_clock(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue)
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    session = user.get(f"/attempts/{attempt['id']}/session").json()
    assert session["status"] == "in_progress" and session["title"] == quiz["title"]
    assert session["subject_name"] == "Biology" and session["limit_seconds"] is None
    assert session["remaining_seconds"] is None and session["server_now"] and session["started_at"]
    assert [q["id"] for q in session["questions"]] == [q["id"] for q in quiz["questions"]]
    assert all(set(q) == {"id", "position", "qtype", "prompt", "options"} for q in session["questions"])
    assert session["answers"] == {} and session["flags"] == []
    # The listing says there is an open attempt, so the hub can offer to resume it.
    assert user.get("/quizzes").json()[0]["open_attempt_id"] == attempt["id"]


def test_a_time_limit_can_be_set_on_the_quiz_or_when_starting(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, time_limit_minutes=30)
    assert quiz["time_limit_minutes"] == 30 and quiz["config"]["time_limit_minutes"] == 30
    assert "sessions" not in quiz["config"] and "chunk_ids" not in quiz["config"]

    first = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    session = user.get(f"/attempts/{first['id']}/session").json()
    assert session["limit_seconds"] == 1800 and 1790 <= session["remaining_seconds"] <= 1800
    # Resuming keeps the attempt and its limit, even if another limit is asked for.
    again = user.post(f"/quizzes/{quiz['id']}/attempts", json={"time_limit_minutes": 5}).json()
    assert again["id"] == first["id"]
    assert user.get(f"/attempts/{first['id']}/session").json()["limit_seconds"] == 1800
    answered = user.post(f"/attempts/{first['id']}/submit", json={"answers": []})
    assert answered.status_code == 200

    # A new attempt may choose its own limit, or none at all.
    second = user.post(f"/quizzes/{quiz['id']}/attempts", json={"time_limit_minutes": 5}).json()
    assert user.get(f"/attempts/{second['id']}/session").json()["limit_seconds"] == 300
    user.post(f"/attempts/{second['id']}/submit", json={"answers": []})
    third = user.post(f"/quizzes/{quiz['id']}/attempts", json={"time_limit_minutes": 0}).json()
    assert user.get(f"/attempts/{third['id']}/session").json()["limit_seconds"] is None
    assert user.get("/quizzes").json()[0]["config"].get("sessions") is None

    assert user.post("/quizzes", json={"subject_id": subject_id, "time_limit_minutes": 0}).status_code == 422
    assert user.post("/quizzes", json={"subject_id": subject_id, "time_limit_minutes": 999}).status_code == 422


# ------------------------------------------------------------------ autosave


def test_answers_and_flags_are_saved_as_a_draft_and_survive_a_reload(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, types=["mcq", "true_false", "short"], count=3)
    first, *_ = quiz["questions"]
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    saved = user.request(
        "PUT", f"/attempts/{attempt['id']}/draft",
        json={"answers": [{"question_id": first["id"], "response": "2"}], "flags": [first["id"]]},
    )
    assert saved.status_code == 200 and saved.json()["saved"] == 1
    session = user.get(f"/attempts/{attempt['id']}/session").json()
    assert session["answers"] == {first["id"]: "2"} and session["flags"] == [first["id"]]

    # A later save without `flags` leaves them alone; an empty list clears them.
    user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": [{"question_id": first["id"], "response": "3"}]})
    session = user.get(f"/attempts/{attempt['id']}/session").json()
    assert session["answers"] == {first["id"]: "3"} and session["flags"] == [first["id"]]
    user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": [], "flags": []})
    assert user.get(f"/attempts/{attempt['id']}/session").json()["flags"] == []

    # A draft is not an answer: nothing is revealed or counted until the attempt is submitted.
    assert user.get(f"/attempts/{attempt['id']}").json()["results"] == []
    assert user.get(f"/quizzes/{quiz['id']}").json()["last_attempt"] is None
    assert user.get("/progress").json()["attempts"] == 0
    assert sql("SELECT count(*) FROM revision_cards WHERE user_id = :u", u=user.id)[0][0] == 0


def test_submitting_after_autosaving_marks_exactly_as_before(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    question = quiz["questions"][0]
    # The student types the right answer; the draft is saved with no score.
    reveal = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    revealed = user.post(f"/attempts/{reveal['id']}/submit", json={"answers": []}).json()
    right = revealed["results"][0]["answer"]

    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": [{"question_id": question["id"], "response": "3"}]})
    done = user.post(
        f"/attempts/{attempt['id']}/submit", json={"answers": [{"question_id": question["id"], "response": right}]}
    ).json()
    assert done["status"] == "completed" and done["points"] == 1 and done["total"] == 1
    assert done["results"][0]["response"] == right and done["results"][0]["feedback"] is None
    assert sql("SELECT count(*) FROM quiz_answers WHERE attempt_id = :a", a=attempt["id"])[0][0] == 1
    # Once submitted, the draft endpoint refuses and the session no longer lists questions.
    late = user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": []})
    assert late.status_code == 409 and late.json()["code"] == "already_submitted"
    assert user.get(f"/attempts/{attempt['id']}/session").json()["questions"] == []


def test_a_draft_for_another_quiz_is_refused(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue)
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    url = f"/attempts/{attempt['id']}/draft"
    assert user.request("PUT", url, json={"answers": [{"question_id": MISSING, "response": "1"}]}).status_code == 422
    assert user.request("PUT", url, json={"answers": [], "flags": [MISSING]}).status_code == 422


def test_when_the_time_runs_out_only_what_was_saved_in_time_counts(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    question = quiz["questions"][0]
    reveal = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    right = user.post(f"/attempts/{reveal['id']}/submit", json={"answers": []}).json()["results"][0]["answer"]

    attempt = user.post(f"/quizzes/{quiz['id']}/attempts", json={"time_limit_minutes": 10}).json()
    user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": [{"question_id": question["id"], "response": right}]})
    sql("UPDATE quiz_attempts SET started_at = now() - interval '2 hours' WHERE id = :a", a=attempt["id"])

    session = user.get(f"/attempts/{attempt['id']}/session").json()
    assert session["remaining_seconds"] == 0
    refused = user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": [{"question_id": question["id"], "response": "3"}]})
    assert refused.status_code == 409 and refused.json()["code"] == "time_up"
    # Submitting still works, but an answer typed after the deadline is ignored: the draft counts.
    done = user.post(
        f"/attempts/{attempt['id']}/submit", json={"answers": [{"question_id": question["id"], "response": "3"}]}
    ).json()
    assert done["status"] == "completed" and done["points"] == 1


def test_an_untimed_attempt_never_runs_out(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, types=["mcq"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    sql("UPDATE quiz_attempts SET started_at = now() - interval '5 days' WHERE id = :a", a=attempt["id"])
    assert user.request("PUT", f"/attempts/{attempt['id']}/draft", json={"answers": []}).status_code == 200
    assert user.get(f"/attempts/{attempt['id']}/session").json()["remaining_seconds"] is None


# ------------------------------------------------------------------ the analysis


def test_the_analysis_breaks_a_result_down_by_document_with_history(  # type: ignore[no-untyped-def]
    make_user, ingest, llm
):
    user = make_user()
    subject_id, material_id = setup(user, ingest, llm)
    quiz = seeded_quiz(user, subject_id, "Check", ["notes.txt", "notes.txt", "gone.pdf", None])
    first = answer_all(user, quiz, 1)   # q1 right; q2, q3, q4 wrong
    second = answer_all(user, quiz, 4)  # all right
    analysis = user.get(f"/attempts/{first['id']}/analysis").json()

    assert analysis["status"] == "completed" and analysis["percent"] == 0.25
    assert analysis["points"] == 1 and analysis["total"] == 4 and analysis["missed"] == 3
    assert analysis["duration_seconds"] is not None and analysis["limit_seconds"] is None
    by_topic = {t["topic"]: t for t in analysis["topics"]}
    assert by_topic["notes.txt"]["answers"] == 2 and by_topic["notes.txt"]["accuracy"] == 0.5
    assert by_topic["notes.txt"]["missed"] == 1 and by_topic["notes.txt"]["material_id"] == material_id
    assert by_topic["gone.pdf"]["accuracy"] == 0 and by_topic["gone.pdf"]["material_id"] is None
    assert by_topic[None]["answers"] == 1
    # Weakest document first; the question with no source document goes last.
    assert [t["topic"] for t in analysis["topics"]] == ["gone.pdf", "notes.txt", None]
    assert by_topic["notes.txt"]["earlier_answers"] == 0 and by_topic["notes.txt"]["earlier_accuracy"] is None

    # The second attempt knows how those documents went before it.
    later = user.get(f"/attempts/{second['id']}/analysis").json()
    assert later["percent"] == 1.0 and later["missed"] == 0
    earlier = {t["topic"]: t for t in later["topics"]}["notes.txt"]
    assert earlier["earlier_answers"] == 2 and earlier["earlier_accuracy"] == 0.5 and earlier["accuracy"] == 1.0
    assert [h["attempt_id"] for h in later["history"]] == [first["id"], second["id"]]
    assert [h["percent"] for h in later["history"]] == [0.25, 1.0]
    # The course average is over the *other* attempts.
    assert later["course"]["name"] == "Biology" and later["course"]["attempts"] == 1
    assert later["course"]["average"] == 0.25 and later["course"]["best"] == 0.25
    assert analysis["course"]["average"] == 1.0

    # Every scored answer made a revision card; the missed ones come back tomorrow.
    assert later["revision"]["cards"] == 4 and later["revision"]["due_now"] == 0
    assert later["revision"]["next_due_at"] is not None
    assert all(q["card"] is not None for q in later["questions"])
    assert [q["position"] for q in later["questions"]] == [1, 2, 3, 4]


def test_the_analysis_waits_for_a_submitted_attempt_and_leaves_unmarked_answers_out(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, types=["short"])
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    blocked = user.get(f"/attempts/{attempt['id']}/analysis")
    assert blocked.status_code == 409 and blocked.json()["code"] == "attempt_in_progress"
    answers = [{"question_id": quiz["questions"][0]["id"], "response": "Light makes food."}]
    user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers})
    waiting = user.get(f"/attempts/{attempt['id']}/analysis").json()
    assert waiting["status"] == "grading" and waiting["percent"] is None and waiting["missed"] == 0
    assert waiting["topics"][0]["answers"] == 0 and waiting["topics"][0]["accuracy"] is None
    assert waiting["questions"][0]["score"] is None and waiting["revision"]["cards"] == 0


def test_a_revision_attempt_without_a_course_has_no_course_figures(  # type: ignore[no-untyped-def]
    make_user, ingest, llm
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = seeded_quiz(user, subject_id, "Check", ["notes.txt"])
    done = answer_all(user, quiz, 0)
    sql("UPDATE quizzes SET subject_id = NULL WHERE id = :q", q=quiz["id"])
    analysis = user.get(f"/attempts/{done['id']}/analysis").json()
    assert analysis["course"] is None and analysis["topics"][0]["earlier_answers"] == 0


# ------------------------------------------------------------------ follow-ups


def test_the_questions_that_were_missed_can_be_practised_again(  # type: ignore[no-untyped-def]
    make_user, ingest, llm
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    quiz = seeded_quiz(user, subject_id, "Check", ["notes.txt", "notes.txt", "other.pdf"])
    done = answer_all(user, quiz, 1)  # question 1 right, 2 and 3 wrong

    made = user.post(f"/attempts/{done['id']}/practise-missed", json={"title": "Missed questions"})
    assert made.status_code == 201, made.text
    practice = made.json()
    assert practice["source"] == "revision" and practice["status"] == "ready"
    assert practice["question_count"] == 2 and practice["title"] == "Missed questions"
    assert practice["subject_id"] == subject_id and practice["config"]["retry_of"] == done["id"]
    detail = user.get(f"/quizzes/{practice['id']}").json()
    assert [q["prompt"] for q in detail["questions"]] == ["Statement 2", "Statement 3"]
    origins = {r[0] for r in sql("SELECT origin_question_id FROM quiz_questions WHERE quiz_id = :q", q=practice["id"])}
    assert origins == {uuid.UUID(q["id"]) for q in quiz["questions"][1:]}

    # Answering it moves the same revision cards the original attempt created (no new cards).
    def boxes() -> list[int]:
        return [b[0] for b in sql("SELECT box FROM revision_cards WHERE user_id = :u ORDER BY box", u=user.id)]

    assert boxes() == [1, 1, 2]
    retake = answer_all(user, detail, 2)
    assert retake["points"] == 2
    assert boxes() == [2, 2, 2]

    perfect = user.get(f"/attempts/{retake['id']}/analysis").json()
    assert perfect["missed"] == 0
    nothing = user.post(f"/attempts/{retake['id']}/practise-missed", json={})
    assert nothing.status_code == 409 and nothing.json()["code"] == "nothing_missed"
    open_attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    blocked = user.post(f"/attempts/{open_attempt['id']}/practise-missed", json={})
    assert blocked.status_code == 409 and blocked.json()["code"] == "attempt_in_progress"


def test_a_failed_quiz_can_be_written_again_with_the_same_settings(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    llm.error = "invalid_key"
    quiz = make_quiz(user, subject_id, generate_quiz, queue, time_limit_minutes=15)
    assert quiz["status"] == "failed" and quiz["error"] == "invalid_key"

    llm.error = None
    again = user.post(f"/quizzes/{quiz['id']}/retry")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "queued" and again.json()["error"] is None
    assert (quiz["id"], user.id) in queue.quiz_jobs
    generate_quiz(quiz["id"], user.id)
    ready = user.get(f"/quizzes/{quiz['id']}").json()
    assert ready["status"] == "ready" and ready["questions"] and ready["time_limit_minutes"] == 15

    refused = user.post(f"/quizzes/{quiz['id']}/retry")
    assert refused.status_code == 409 and refused.json()["code"] == "not_failed"


def test_retrying_needs_a_key(make_user, ingest, llm, queue, generate_quiz):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id, _ = setup(user, ingest, llm)
    llm.error = "invalid_key"
    quiz = make_quiz(user, subject_id, generate_quiz, queue)
    user.request("DELETE", "/settings/providers/openai")
    response = user.post(f"/quizzes/{quiz['id']}/retry")
    assert response.status_code == 409 and response.json()["code"] == "no_provider_key"


def test_a_quiz_can_be_made_from_one_document(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    user = make_user()
    subject_id, material_id = setup(user, ingest, llm)
    other = user.post(
        f"/subjects/{subject_id}/materials",
        files={"file": ("history.txt", b"The Battle of Plassey was fought in 1757 between the British East India "
               b"Company and the Nawab of Bengal, and it opened the way for Company rule across eastern India "
               b"during the following decades of the eighteenth century.")},
    ).json()
    ingest(other["id"], user.id)
    quiz = make_quiz(user, subject_id, generate_quiz, queue, count=5, material_id=material_id)
    assert quiz["status"] == "ready" and quiz["config"]["focus"] == "notes.txt"
    assert "chunk_ids" not in quiz["config"]
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": []}).json()
    assert {r["source"]["filename"] for r in done["results"]} == {"notes.txt"}
    assert user.get(f"/attempts/{attempt['id']}/analysis").json()["topics"][0]["material_id"] == material_id

    stray = user.post("/quizzes", json={"subject_id": subject_id, "material_id": MISSING})
    assert stray.status_code == 404


# ------------------------------------------------------------------ privacy


def test_another_student_cannot_reach_any_of_it(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    owner, other = make_user(), make_user()
    subject_id, material_id = setup(owner, ingest, llm)
    quiz = seeded_quiz(owner, subject_id, "Check", ["notes.txt"])
    done = answer_all(owner, quiz, 0)
    open_attempt = owner.post(f"/quizzes/{quiz['id']}/attempts").json()

    assert other.get(f"/attempts/{open_attempt['id']}/session").status_code == 404
    assert other.request("PUT", f"/attempts/{open_attempt['id']}/draft", json={"answers": []}).status_code == 404
    assert other.get(f"/attempts/{done['id']}/analysis").status_code == 404
    assert other.post(f"/attempts/{done['id']}/practise-missed", json={}).status_code == 404
    assert other.post(f"/quizzes/{quiz['id']}/retry").status_code == 404
    # Another student's material cannot be used either.
    other.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    mine = other.post("/subjects", json={"name": "Mine"}).json()["id"]
    assert other.post("/quizzes", json={"subject_id": mine, "material_id": material_id}).status_code in (404, 409)
    # The owner's draft cannot be overwritten by guessing question ids.
    question_id = quiz["questions"][0]["id"]
    forged = other.request("PUT", f"/attempts/{open_attempt['id']}/draft", json={"answers": [{"question_id": question_id, "response": "x"}]})
    assert forged.status_code == 404
    assert sql("SELECT count(*) FROM quiz_answers WHERE attempt_id = :a", a=open_attempt["id"])[0][0] == 0


def test_the_new_routes_need_a_signed_in_student(anon):  # type: ignore[no-untyped-def]
    for method, path in (
        ("GET", f"/attempts/{MISSING}/session"), ("PUT", f"/attempts/{MISSING}/draft"),
        ("GET", f"/attempts/{MISSING}/analysis"), ("POST", f"/attempts/{MISSING}/practise-missed"),
        ("POST", f"/quizzes/{MISSING}/retry"),
    ):
        assert anon.request(method, path, json={}).status_code == 401, path


# ------------------------------------------------------------------ general knowledge


def test_a_quiz_can_be_about_a_topic_from_general_knowledge(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, queue, generate_quiz
):
    def general(system: str, messages: list[ChatMessage]) -> list[str]:
        plan = re.findall(r"- Question (\d+): (\w+)", messages[-1].content)
        return [json.dumps({"questions": [
            {"passage": int(n), "type": kind, "question": f"General question {n}?", "explanation": "Known fact.",
             "options": ["A", "B", "C", "D"], "answer": 0} if kind == "mcq"
            else {"passage": int(n), "type": kind, "question": f"General question {n}?", "explanation": "Known fact.", "answer": True}
            for n, kind in plan
        ]})]

    user = make_user()
    subject_id = user.post("/subjects", json={"name": "Physics"}).json()["id"]  # no materials at all
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.responder = general
    body = {"subject_id": subject_id, "count": 3, "types": ["mcq", "true_false"]}
    assert user.post("/quizzes", json={**body, "basis": "general"}).status_code == 422  # needs a topic
    assert user.post("/quizzes", json=body).json()["code"] == "no_materials"
    made = user.post("/quizzes", json={**body, "basis": "general", "topic": "Thermodynamics"})
    assert made.status_code == 201, made.text
    assert made.json()["title"] == "Thermodynamics" and made.json()["config"]["basis"] == "general"
    generate_quiz(made.json()["id"], user.id)
    quiz = user.get(f"/quizzes/{made.json()['id']}").json()
    assert quiz["status"] == "ready" and len(quiz["questions"]) == 3
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    done = user.post(f"/attempts/{attempt['id']}/submit", json={"answers": []}).json()
    assert all(r["source"] is None for r in done["results"])
    analysis = user.get(f"/attempts/{attempt['id']}/analysis").json()
    assert [t["topic"] for t in analysis["topics"]] == [None]
