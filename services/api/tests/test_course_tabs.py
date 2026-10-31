"""The course workspace: analytics, the course's assignments, renaming a module."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from mindnest_api.llm import ChatMessage

KEY = "sk-test-1234567890abcdef"
NOTES = (
    b"Photosynthesis is the process by which green plants use sunlight to make food from carbon "
    b"dioxide and water. It takes place in the chloroplasts, which contain the green pigment "
    b"chlorophyll, and it releases oxygen as a by-product that animals breathe in. "
    b"The light reactions capture energy while the Calvin cycle builds sugars from carbon dioxide."
)


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


def course_with_notes(user, ingest, module=None):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": "Biology"}).json()["id"]
    extra = {"data": {"module": module}} if module else {}
    material = user.post(
        f"/subjects/{subject_id}/materials", files={"file": ("notes.txt", NOTES)}, **extra
    ).json()
    ingest(material["id"], user.id)
    return subject_id


def finish_a_quiz(user, subject_id, llm, generate_quiz):  # type: ignore[no-untyped-def]
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    llm.responder = well_behaved
    quiz = user.post("/quizzes", json={"subject_id": subject_id, "count": 3, "types": ["mcq"]}).json()
    generate_quiz(quiz["id"], user.id)
    quiz = user.get(f"/quizzes/{quiz['id']}").json()
    attempt = user.post(f"/quizzes/{quiz['id']}/attempts").json()
    answers = [{"question_id": q["id"], "response": ""} for q in quiz["questions"]]
    assert user.post(f"/attempts/{attempt['id']}/submit", json={"answers": answers}).status_code == 200
    return quiz


# ------------------------------------------------------------------------------- analytics


def test_a_new_course_has_empty_analytics_and_suggests_uploading(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = user.post("/subjects", json={"name": "Empty course"}).json()["id"]
    body = user.get(f"/subjects/{subject_id}/analytics").json()
    assert body["attempts"] == [] and body["trend"] is None and body["by_type"] == []
    assert len(body["weeks"]) == 8 and all(w["attempts"] == 0 for w in body["weeks"])
    assert body["progress"] is None  # nothing measured is not 0% and not 100%
    assert body["coverage"]["practised_share"] is None
    assert [r["kind"] for r in body["recommendations"]] == ["upload_first"]


def test_a_course_with_notes_but_no_quiz_suggests_a_first_quiz(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = course_with_notes(user, ingest)
    kinds = [r["kind"] for r in user.get(f"/subjects/{subject_id}/analytics").json()["recommendations"]]
    assert kinds == ["first_quiz"]


def test_a_finished_quiz_shows_in_scores_types_weeks_and_coverage(  # type: ignore[no-untyped-def]
    make_user, ingest, llm, generate_quiz
):
    user = make_user()
    subject_id = course_with_notes(user, ingest)
    quiz = finish_a_quiz(user, subject_id, llm, generate_quiz)

    body = user.get(f"/subjects/{subject_id}/analytics").json()
    assert [a["quiz_id"] for a in body["attempts"]] == [quiz["id"]]
    assert 0 <= body["attempts"][0]["percent"] <= 1
    assert [t["qtype"] for t in body["by_type"]] == ["mcq"] and body["by_type"][0]["answers"] >= 1
    assert body["weeks"][-1]["attempts"] == 1  # the last entry is this week
    assert body["coverage"]["documents_ready"] == 1 and body["coverage"]["documents_practised"] == 1
    assert body["coverage"]["practised_share"] == 1.0
    assert body["progress"] is not None
    assert body["trend"] is None  # four attempts are needed to call a direction


def test_assignments_show_in_analytics_and_overdue_work_comes_first(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = course_with_notes(user, ingest)
    late = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    soon = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    user.post("/assignments", json={"title": "Lab report", "subject_id": subject_id, "due_at": late})
    user.post("/assignments", json={"title": "Essay", "subject_id": subject_id, "due_at": soon})

    body = user.get(f"/subjects/{subject_id}/analytics").json()
    assert body["assignments"]["overdue"] == 1 and body["assignments"]["todo"] == 2
    assert body["assignments"]["next_due_title"] == "Essay"
    first = body["recommendations"][0]
    assert first["kind"] == "deadline" and first["label"] == "Lab report"


def test_analytics_of_someone_elses_course_is_not_found(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    subject_id = owner.post("/subjects", json={"name": "Private"}).json()["id"]
    assert other.get(f"/subjects/{subject_id}/analytics").status_code == 404
    assert other.get(f"/subjects/{subject_id}/assignments").status_code == 404
    assert other.post(f"/subjects/{subject_id}/modules/rename", json={"old": "A", "new": "B"}).status_code == 404


# ----------------------------------------------------------------------------- assignments


def test_a_course_lists_only_its_own_assignments(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    first = user.post("/subjects", json={"name": "First"}).json()["id"]
    second = user.post("/subjects", json={"name": "Second"}).json()["id"]
    user.post("/assignments", json={"title": "In first", "subject_id": first})
    user.post("/assignments", json={"title": "In second", "subject_id": second})
    user.post("/assignments", json={"title": "No course"})

    titles = [a["title"] for a in user.get(f"/subjects/{first}/assignments").json()]
    assert titles == ["In first"]


# --------------------------------------------------------------------------------- modules


def modules_of(user, subject_id):  # type: ignore[no-untyped-def]
    return [m["module"] for m in user.get(f"/subjects/{subject_id}/materials").json()]


def test_a_module_can_be_renamed_merged_and_emptied(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = course_with_notes(user, ingest, module="Unit 1")
    path = f"/subjects/{subject_id}/modules/rename"

    renamed = user.post(path, json={"old": "unit  1", "new": "Unit One"})  # case and spacing do not matter
    assert renamed.status_code == 200 and renamed.json() == {"updated": 1}
    assert modules_of(user, subject_id) == ["Unit One"]

    assert user.post(path, json={"old": "Unit One", "new": "   "}).json() == {"updated": 1}
    assert modules_of(user, subject_id) == [None]

    # Files in no module can be put into one.
    assert user.post(path, json={"old": None, "new": "Unit 2"}).json() == {"updated": 1}
    assert modules_of(user, subject_id) == ["Unit 2"]


def test_a_module_rename_needs_something_to_change(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = course_with_notes(user, ingest, module="Unit 1")
    path = f"/subjects/{subject_id}/modules/rename"
    assert user.post(path, json={"old": None, "new": None}).status_code == 422
    assert user.post(path, json={"old": "Unit 1", "new": "Unit 1"}).status_code == 422
    assert user.post(path, json={"old": "Unit 1", "new": "x" * 81}).status_code == 422
    assert modules_of(user, subject_id) == ["Unit 1"]
    # Nothing carries that name, so nothing changes.
    assert user.post(path, json={"old": "Missing", "new": "Other"}).json() == {"updated": 0}
