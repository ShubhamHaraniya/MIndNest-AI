"""Course figures and topic progress for the Subjects pages."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text


def owner_sql(query: str, **params: Any) -> list[dict[str, Any]]:
    """Run one statement as the table owner (row-level security off) and commit it, to set up
    data the API has no way to create (quiz attempts, exams, files in a given state)."""

    async def go() -> list[dict[str, Any]]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return [dict(r) for r in result.mappings().all()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _subject(user, name="Operating Systems", **extra):  # type: ignore[no-untyped-def]
    response = user.post("/subjects", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _material(  # type: ignore[no-untyped-def]
    user, subject_id, filename, kind="material", module=None, status="ready"
) -> str:
    row = owner_sql(
        "INSERT INTO materials (subject_id, owner_id, kind, filename, mime_type, size_bytes, "
        "storage_key, status, module) VALUES (:s, :u, :k, :f, 'application/pdf', 100, :key, :st, :m) "
        "RETURNING id",
        s=subject_id, u=user.id, k=kind, f=filename, key=f"materials/{user.id}/{filename}",
        st=status, m=module,
    )[0]
    return str(row["id"])


def _attempt(user, subject_id, filename, scores, *, title="Check", status="completed"):  # type: ignore[no-untyped-def]
    """A finished quiz attempt whose questions all cite `filename`, answered with `scores`."""
    quiz = owner_sql(
        "INSERT INTO quizzes (user_id, subject_id, title, status) VALUES (:u, :s, :t, 'ready') RETURNING id",
        u=user.id, s=subject_id, t=title,
    )[0]["id"]
    attempt = owner_sql(
        "INSERT INTO quiz_attempts (quiz_id, user_id, status, points, total, finished_at) "
        "VALUES (:q, :u, :st, :p, :t, now()) RETURNING id",
        q=quiz, u=user.id, st=status, p=sum(scores), t=len(scores),
    )[0]["id"]
    for position, score in enumerate(scores, start=1):
        question = owner_sql(
            "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, answer, source) "
            "VALUES (:q, :u, :p, 'short', 'Q?', 'A', CAST(:src AS jsonb)) RETURNING id",
            q=quiz, u=user.id, p=position, src=json.dumps({"filename": filename}),
        )[0]["id"]
        owner_sql(
            "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response, score) "
            "VALUES (:a, :q, :u, 'x', :s)",
            a=attempt, q=question, u=user.id, s=score,
        )
    return quiz


def _exam(user, subject_id, title, days):  # type: ignore[no-untyped-def]
    on = (datetime.now(UTC) + timedelta(days=days)).date()
    owner_sql(
        "INSERT INTO exams (user_id, subject_id, title, exam_on) VALUES (:u, :s, :t, :d)",
        u=user.id, s=subject_id, t=title, d=on,
    )


# ------------------------------------------------------------------------------ course list


def test_course_list_carries_every_figure_in_one_response(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user, "Operating Systems", course_code="CS301", semester="5")
    _material(user, sid, "lecture.pdf", module="Unit 1")
    _material(user, sid, "paper-2023.pdf", kind="past_paper")
    _material(user, sid, "notes.md", kind="note", status="processing")
    _material(user, sid, "broken.pdf", status="failed")
    _attempt(user, sid, "lecture.pdf", [1, 0, 1, 1])
    _exam(user, sid, "Midterm", 6)
    _exam(user, sid, "Final", 40)
    _exam(user, sid, "Old exam", -3)  # in the past: never the "next" exam

    body = user.get("/courses").json()
    assert body["total"] == 1
    course = body["items"][0]
    assert course["id"] == sid
    assert (course["name"], course["course_code"], course["semester"]) == ("Operating Systems", "CS301", "5")
    assert course["documents"] == 4
    assert course["documents_ready"] == 2
    assert course["documents_working"] == 1
    assert course["documents_failed"] == 1
    assert course["past_papers"] == 1
    assert course["notes"] == 1
    assert course["quizzes"] == 1
    assert course["quiz_attempts"] == 1
    assert course["quiz_average"] == 0.75
    assert course["next_exam_title"] == "Midterm"
    assert course["next_exam_days"] == 6
    assert course["last_activity_at"] is not None


def test_a_course_with_nothing_in_it_has_empty_figures(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    course = user.get("/courses").json()["items"][0]
    assert course["id"] == sid
    assert course["documents"] == course["past_papers"] == course["notes"] == course["quiz_attempts"] == 0
    assert course["quiz_average"] is None
    assert course["next_exam_title"] is None
    assert course["next_exam_days"] is None


def test_course_list_filters_by_state_and_search_and_orders_by_activity(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    a = _subject(user, "Algebra", course_code="MA201")
    b = _subject(user, "Biology")
    c = _subject(user, "Chemistry")
    user.post(f"/subjects/{c}/archive")
    _material(user, a, "a.pdf")  # Algebra has the newest activity
    ids = [item["id"] for item in user.get("/courses").json()["items"]]
    assert ids == [a, b]
    assert [i["id"] for i in user.get("/courses?state=archived").json()["items"]] == [c]
    assert user.get("/courses?state=all").json()["total"] == 3
    assert [i["id"] for i in user.get("/courses?q=ma2").json()["items"]] == [a]  # by code
    assert [i["id"] for i in user.get("/courses?q=BIO").json()["items"]] == [b]  # by name
    assert user.get("/courses?q=%25").json()["total"] == 0  # a percent sign is not a wildcard
    assert user.get("/courses?state=weird").status_code == 422


def test_course_list_and_overview_hide_other_students_courses(make_user) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    mine = _subject(alice, "Mine")
    theirs = _subject(bob, "Theirs")
    _material(bob, theirs, "secret.pdf")
    assert [i["id"] for i in alice.get("/courses?state=all").json()["items"]] == [mine]
    assert alice.get(f"/subjects/{theirs}/overview").status_code == 404
    assert alice.get(f"/subjects/{theirs}/progress").status_code == 404
    assert alice.get("/subjects/not-a-uuid/progress").status_code == 422


def test_course_routes_need_a_signed_in_student(client) -> None:  # type: ignore[no-untyped-def]
    client.cookies.clear()
    assert client.get("/api/v1/courses").status_code == 401
    assert client.get("/api/v1/subjects/00000000-0000-0000-0000-000000000000/progress").status_code == 401


# ---------------------------------------------------------------------------------- overview


def test_overview_returns_figures_and_upcoming_exams_in_order(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    _exam(user, sid, "Final", 30)
    _exam(user, sid, "Midterm", 5)
    _exam(user, sid, "Gone", -1)
    body = user.get(f"/subjects/{sid}/overview").json()
    assert body["course"]["id"] == sid
    assert [(e["title"], e["days_left"]) for e in body["exams"]] == [("Midterm", 5), ("Final", 30)]
    assert body["course"]["next_exam_title"] == "Midterm"


# ----------------------------------------------------------------------------------- progress


def test_progress_is_per_document_and_per_module(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    sched = _material(user, sid, "sched.pdf", module="Unit 2")
    sync = _material(user, sid, "sync.pdf", module="Unit 10")
    memory = _material(user, sid, "memory.pdf", module="Unit 2")
    _material(user, sid, "unfiled.pdf")
    _attempt(user, sid, "sched.pdf", [1, 0, 0, 0])  # 25%: weak
    _attempt(user, sid, "memory.pdf", [1, 1, 1])  # 100%
    _attempt(user, sid, "sync.pdf", [0.5, 0.5])  # 50% but only two answers: not weak

    progress = user.get(f"/subjects/{sid}/progress").json()
    docs = {d["filename"]: d for d in progress["documents"]}
    assert docs["sched.pdf"]["material_id"] == sched
    assert (docs["sched.pdf"]["answers"], docs["sched.pdf"]["accuracy"], docs["sched.pdf"]["weak"]) == (4, 0.25, True)
    assert docs["memory.pdf"]["accuracy"] == 1.0 and docs["memory.pdf"]["weak"] is False
    assert docs["sync.pdf"]["material_id"] == sync
    assert docs["sync.pdf"]["accuracy"] == 0.5 and docs["sync.pdf"]["weak"] is False
    assert docs["unfiled.pdf"]["answers"] == 0 and docs["unfiled.pdf"]["accuracy"] is None
    assert docs["sched.pdf"]["last_practised_at"] is not None
    assert docs["unfiled.pdf"]["last_practised_at"] is None
    assert memory in {d["material_id"] for d in progress["documents"]}

    # Modules sort naturally (Unit 2 before Unit 10), files without a module come last, and
    # accuracy is points over answers across the module's documents.
    assert [m["module"] for m in progress["modules"]] == ["Unit 2", "Unit 10", None]
    unit2 = progress["modules"][0]
    assert (unit2["documents"], unit2["answers"], unit2["accuracy"]) == (2, 7, round(4 / 7, 4))
    assert unit2["weak"] is True
    assert progress["modules"][2]["accuracy"] is None and progress["modules"][2]["weak"] is False

    summary = progress["summary"]
    assert summary["answers"] == 9
    assert summary["accuracy"] == round(5 / 9, 4)
    assert summary["attempts"] == 3
    assert summary["weak_documents"] == 1


def test_progress_ignores_unfinished_attempts_and_unmarked_answers(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    _material(user, sid, "a.pdf")
    quiz = _attempt(user, sid, "a.pdf", [1, 1], status="grading")  # not completed
    assert user.get(f"/subjects/{sid}/progress").json()["summary"]["answers"] == 0
    # A completed attempt with one answer the AI has not marked yet (score NULL) counts only the marked one.
    attempt = owner_sql(
        "INSERT INTO quiz_attempts (quiz_id, user_id, status, points, total, finished_at) "
        "VALUES (:q, :u, 'completed', 0, 1, now()) RETURNING id",
        q=quiz, u=user.id,
    )[0]["id"]
    question = owner_sql("SELECT id FROM quiz_questions WHERE quiz_id = :q LIMIT 1", q=quiz)[0]["id"]
    owner_sql(
        "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response, score) VALUES (:a, :q, :u, 'x', NULL)",
        a=attempt, q=question, u=user.id,
    )
    assert user.get(f"/subjects/{sid}/progress").json()["summary"]["answers"] == 0


def test_answers_for_a_deleted_file_stay_in_the_totals_but_not_in_a_module(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    _material(user, sid, "kept.pdf", module="Unit 1")
    _attempt(user, sid, "gone.pdf", [1, 1, 0])
    progress = user.get(f"/subjects/{sid}/progress").json()
    orphan = next(d for d in progress["documents"] if d["filename"] == "gone.pdf")
    assert orphan["material_id"] is None and orphan["answers"] == 3
    assert progress["summary"]["answers"] == 3
    assert progress["modules"][0]["answers"] == 0


def test_a_deleted_material_is_not_listed(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    mid = _material(user, sid, "x.pdf")
    owner_sql("UPDATE materials SET deleted_at = now() WHERE id = :id", id=mid)
    assert user.get(f"/subjects/{sid}/progress").json()["documents"] == []
    assert user.get(f"/subjects/{sid}/overview").json()["course"]["documents"] == 0


def test_row_level_security_keeps_other_students_answers_out_of_progress(make_user) -> None:  # type: ignore[no-untyped-def]
    """Even a quiz row that points at Alice's course but belongs to Bob must never reach Alice."""
    alice, bob = make_user(), make_user()
    sid = _subject(alice)
    _material(alice, sid, "shared-name.pdf")
    _attempt(bob, sid, "shared-name.pdf", [0, 0, 0, 0])  # owned by Bob, filed under Alice's course
    progress = alice.get(f"/subjects/{sid}/progress").json()
    assert progress["summary"]["answers"] == 0
    assert progress["summary"]["attempts"] == 0
    assert all(d["answers"] == 0 for d in progress["documents"])
    assert alice.get("/courses").json()["items"][0]["quiz_attempts"] == 0
    # ... and Bob cannot read Alice's course at all.
    assert bob.get(f"/subjects/{sid}/progress").status_code == 404


def test_two_files_with_the_same_name_do_not_double_count(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    sid = _subject(user)
    _material(user, sid, "dup.pdf")
    _material(user, sid, "dup.pdf")
    _attempt(user, sid, "dup.pdf", [1, 1, 1])
    docs: list[dict[str, Any]] = user.get(f"/subjects/{sid}/progress").json()["documents"]
    assert sorted(d["answers"] for d in docs) == [0, 3]
