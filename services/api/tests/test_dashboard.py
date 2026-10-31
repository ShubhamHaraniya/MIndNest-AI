"""The dashboard, the notification bell and search, against a real database."""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from mindnest_api.routes.dashboard import streak
from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text


def sql(query: str, **params: Any) -> list[Any]:
    async def go() -> list[Any]:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def today() -> date:
    return datetime.now(UTC).date()


def day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def make_subject(user, name="Biology"):  # type: ignore[no-untyped-def]
    return user.post("/subjects", json={"name": name}).json()["id"]


def add_attempt(user, subject_id, filename, scores):  # type: ignore[no-untyped-def]
    quiz = sql(
        "INSERT INTO quizzes (user_id, subject_id, title, status) VALUES (:u, :s, 'Cells quiz', 'ready') RETURNING id",
        u=user.id, s=subject_id,
    )[0][0]
    attempt = sql(
        "INSERT INTO quiz_attempts (quiz_id, user_id, status, points, total, finished_at) "
        "VALUES (:q, :u, 'completed', :p, :t, now()) RETURNING id",
        q=quiz, u=user.id, p=sum(scores), t=len(scores),
    )[0][0]
    for position, score in enumerate(scores, start=1):
        question = sql(
            "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, answer, source) "
            "VALUES (:q, :u, :p, 'short', 'Q?', 'A', CAST(:src AS jsonb)) RETURNING id",
            q=quiz, u=user.id, p=position, src=json.dumps({"filename": filename}),
        )[0][0]
        sql(
            "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response, score) VALUES (:a, :q, :u, 'x', :s)",
            a=attempt, q=question, u=user.id, s=score,
        )


# --------------------------------------------------------------------------------- streak


def test_the_streak_counts_days_in_a_row_and_forgives_a_day_not_over_yet() -> None:
    t = date(2026, 10, 29)
    assert streak(set(), t) == 0
    assert streak({t, t - timedelta(days=1), t - timedelta(days=2)}, t) == 3
    assert streak({t - timedelta(days=1), t - timedelta(days=2)}, t) == 2  # today not studied yet
    assert streak({t, t - timedelta(days=2)}, t) == 1  # a gap ends it
    assert streak({t - timedelta(days=2)}, t) == 0


# ------------------------------------------------------------------------------- dashboard


def test_a_new_student_gets_an_empty_but_complete_dashboard(make_user) -> None:  # type: ignore[no-untyped-def]
    body = make_user().get("/dashboard").json()
    assert body["stats"] == {
        "subjects": 0, "materials": 0, "materials_ready": 0, "quiz_attempts": 0,
        "quiz_average": None, "revision_due": 0, "conversations": 0,
    }
    assert body["streak_days"] == 0 and body["subjects"] == [] and body["weak_topics"] == []
    assert body["deadlines"] == [] and body["quiz_trend"] == [] and body["recent_chats"] == []
    assert body["today_tasks"] == {"total": 0, "done": 0, "minutes_total": 0, "minutes_done": 0}
    assert len(body["study_week"]) == 7 and all(d["minutes_done"] == 0 for d in body["study_week"])


def test_the_dashboard_summarises_the_students_real_data(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user)
    user.post("/exams", json={"title": "Midterm", "exam_on": day(5), "subject_id": subject})
    user.post("/exams", json={"title": "Far away", "exam_on": day(200)})
    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    user.post("/assignments", json={"title": "Lab report", "due_at": due, "subject_id": subject})
    done = user.post("/planner/tasks", json={"title": "Read ch. 1", "planned_for": day(0), "minutes": 40}).json()
    user.patch(f"/planner/tasks/{done['id']}", json={"status": "done"})
    user.post("/planner/tasks", json={"title": "Practice", "planned_for": day(0), "minutes": 20})
    add_attempt(user, subject, "cells.pdf", [1, 0, 0, 1])
    user.post("/conversations", json={})

    body = user.get("/dashboard").json()
    assert body["stats"]["subjects"] == 1 and body["stats"]["quiz_attempts"] == 1
    assert body["stats"]["quiz_average"] == 0.5 and body["stats"]["conversations"] == 1
    assert body["today_tasks"] == {"total": 2, "done": 1, "minutes_total": 60, "minutes_done": 40}
    assert body["streak_days"] == 1  # a finished task and a quiz both count for today
    assert body["study_week"][-1]["minutes_done"] == 40 and body["study_week"][-1]["minutes_planned"] == 60
    assert [d["title"] for d in body["deadlines"]] == ["Lab report", "Midterm"]  # sorted by date; 200 days is out
    assert body["deadlines"][0]["kind"] == "assignment" and body["deadlines"][1]["days_left"] == 5
    assert body["subjects"][0]["quiz_average"] == 0.5 and body["subjects"][0]["quiz_attempts"] == 1
    assert body["quiz_trend"][0]["percent"] == 0.5


def test_weak_topics_need_enough_answers_and_a_low_score(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user)
    add_attempt(user, subject, "weak.pdf", [0, 0, 1])      # 33 %, 3 answers: weak
    add_attempt(user, subject, "strong.pdf", [1, 1, 1])    # 100 %: not weak
    add_attempt(user, subject, "few.pdf", [0, 0])          # only 2 answers: too little to say
    weak = user.get("/dashboard").json()["weak_topics"]
    assert [w["material"] for w in weak] == ["weak.pdf"]
    assert weak[0]["subject_name"] == "Biology" and weak[0]["answers"] == 3


def test_one_students_dashboard_never_shows_anothers_data(make_user) -> None:  # type: ignore[no-untyped-def]
    mine, theirs = make_user(), make_user()
    make_subject(theirs, "Secret")
    theirs.post("/exams", json={"title": "Theirs", "exam_on": day(2)})
    body = mine.get("/dashboard").json()
    assert body["stats"]["subjects"] == 0 and body["deadlines"] == []


def test_the_dashboard_needs_sign_in(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/dashboard").status_code == 401


# ---------------------------------------------------------------------------- notifications


def kinds(user) -> dict[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    return {n["kind"]: n for n in user.get("/notifications").json()["items"]}


def test_a_quiet_student_has_no_notifications(make_user) -> None:  # type: ignore[no-untyped-def]
    assert make_user().get("/notifications").json() == {"unread": 0, "items": []}


def test_notifications_are_built_from_the_students_own_data(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user)
    user.post("/exams", json={"title": "Midterm", "exam_on": day(2), "subject_id": subject})
    user.post("/exams", json={"title": "Later", "exam_on": day(30)})  # outside the window
    user.post("/assignments", json={"title": "Essay", "due_at": (datetime.now(UTC) - timedelta(days=3)).isoformat()})
    user.post("/planner/tasks", json={"title": "Read", "planned_for": day(0), "minutes": 25})
    sql(
        "INSERT INTO revision_cards (user_id, subject_id, origin_question_id, qtype, prompt, answer, due_at) "
        "VALUES (:u, :s, :o, 'short', 'Q?', 'A', now() - interval '1 day')",
        u=user.id, s=subject, o=str(uuid.uuid4()),
    )
    found = kinds(user)
    assert set(found) == {"exam_soon", "assignment_overdue", "revision_due", "tasks_today"}
    assert found["exam_soon"]["params"]["days"] == 2 and found["exam_soon"]["params"]["title"] == "Midterm"
    assert found["assignment_overdue"]["severity"] == "danger" and found["assignment_overdue"]["params"]["days"] == 3
    assert found["revision_due"]["params"]["count"] == 1
    assert found["tasks_today"]["params"] == {"count": 1, "minutes": 25}
    items = user.get("/notifications").json()["items"]
    assert items[0]["kind"] == "assignment_overdue"  # most urgent first


def test_reading_a_notification_clears_it_and_a_closer_exam_speaks_again(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    exam = user.post("/exams", json={"title": "Midterm", "exam_on": day(6)}).json()
    first = user.get("/notifications").json()
    assert first["unread"] == 1
    key = first["items"][0]["key"]
    assert user.post("/notifications/read", json={"keys": [key]}).status_code == 204
    after = user.get("/notifications").json()
    assert after["unread"] == 0 and after["items"][0]["read"] is True
    user.patch(f"/exams/{exam['id']}", json={"exam_on": day(1)})  # now it is tomorrow
    again = user.get("/notifications").json()
    assert again["unread"] == 1 and again["items"][0]["key"] != key and again["items"][0]["severity"] == "danger"


def test_mark_all_read(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    user.post("/exams", json={"title": "A", "exam_on": day(1)})
    user.post("/planner/tasks", json={"title": "Read", "planned_for": day(0)})
    assert user.get("/notifications").json()["unread"] == 2
    assert user.post("/notifications/read-all").status_code == 204
    assert user.get("/notifications").json()["unread"] == 0


def test_read_marks_are_private_and_validated(make_user) -> None:  # type: ignore[no-untyped-def]
    mine, other = make_user(), make_user()
    mine.post("/exams", json={"title": "A", "exam_on": day(1)})
    other.post("/exams", json={"title": "B", "exam_on": day(1)})
    mine.post("/notifications/read-all")
    assert other.get("/notifications").json()["unread"] == 1
    assert mine.post("/notifications/read", json={"keys": []}).status_code == 422


def test_a_failed_upload_and_a_lapsed_calendar_are_reported(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user)
    sql(
        "INSERT INTO materials (owner_id, subject_id, filename, kind, mime_type, size_bytes, status, error, storage_key) "
        "VALUES (:u, :s, 'broken.pdf', 'material', 'application/pdf', 10, 'failed', 'parse_failed', :k)",
        u=user.id, s=subject, k=str(uuid.uuid4()),
    )
    sql(
        "INSERT INTO google_calendar_links (user_id, refresh_token_enc, needs_reconnect) VALUES (:u, 'x', true)",
        u=user.id,
    )
    found = kinds(user)
    assert found["material_failed"]["params"] == {"filename": "broken.pdf"}
    assert found["calendar_reconnect"]["href"] == "/calendar"


# --------------------------------------------------------------------------------- search


def test_search_ignores_very_short_queries(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    make_subject(user)
    body = user.get("/search", params={"q": "b"}).json()
    assert body["subjects"] == [] and body["query"] == "b"


def test_search_finds_things_across_the_app(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user, "Biology")
    user.post("/exams", json={"title": "Biology midterm", "exam_on": day(9)})
    user.post("/assignments", json={"title": "Biology lab", "subject_id": subject})
    user.post("/conversations", json={"subject_id": subject})
    sql("UPDATE conversations SET title = 'Biology doubts' WHERE user_id = :u", u=user.id)
    add_attempt(user, subject, "cells.pdf", [1])
    sql("UPDATE quizzes SET title = 'Biology quiz' WHERE user_id = :u", u=user.id)
    body = user.get("/search", params={"q": "biology"}).json()
    assert [h["title"] for h in body["subjects"]] == ["Biology"]
    assert body["subjects"][0]["href"] == f"/subjects/{subject}"
    assert [h["title"] for h in body["assignments"]] == ["Biology lab"]
    assert [h["title"] for h in body["quizzes"]] == ["Biology quiz"]
    assert [h["title"] for h in body["conversations"]] == ["Biology doubts"]
    assert body["conversations"][0]["href"].startswith("/chat?c=")
    assert [h["title"] for h in body["exams"]] == ["Biology midterm"]


def test_search_treats_wildcards_as_plain_text_and_is_private(make_user) -> None:  # type: ignore[no-untyped-def]
    mine, other = make_user(), make_user()
    make_subject(mine, "100% Chemistry")
    make_subject(mine, "Physics")
    make_subject(other, "100% Secret")
    assert [h["title"] for h in mine.get("/search", params={"q": "100%"}).json()["subjects"]] == ["100% Chemistry"]
    assert mine.get("/search", params={"q": "%%"}).json()["subjects"] == []
    assert mine.get("/search", params={"q": "secret"}).json()["subjects"] == []


def test_search_needs_sign_in(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/search", params={"q": "abc"}).status_code == 401


# ---------------------------------------------------------------------------- the workbench


def test_a_new_student_has_no_course_and_an_empty_workbench(make_user) -> None:  # type: ignore[no-untyped-def]
    body = make_user().get("/dashboard").json()
    assert body["course"] is None and body["schedule"] == [] and body["recent_documents"] == []
    assert body["assignments_due"] == [] and body["activity"] == []
    assert len(body["week"]) == 7 and body["daily_minutes"] == 90


def test_the_workbench_follows_the_chosen_course(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    biology = make_subject(user, "Biology")
    physics = make_subject(user, "Physics")
    user.post("/exams", json={"title": "Physics midterm", "exam_on": day(3), "subject_id": physics})
    add_attempt(user, biology, "cells.pdf", [0, 0, 1])
    add_attempt(user, physics, "waves.pdf", [0, 0, 0])
    task = user.post(
        "/planner/tasks", json={"title": "Waves", "planned_for": day(0), "minutes": 30, "subject_id": physics}
    ).json()
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    user.post("/assignments", json={"title": "Lab 2", "due_at": due, "subject_id": physics})

    chosen = user.get("/dashboard", params={"course": physics}).json()
    assert chosen["course"]["id"] == physics and chosen["course"]["next_exam_days"] == 3
    assert chosen["course"]["quiz_attempts"] == 1
    assert [w["material"] for w in chosen["weak_topics"]] == ["waves.pdf"]  # only this course's topics
    assert [t["id"] for t in chosen["schedule"]] == [task["id"]]
    assert chosen["schedule"][0]["subject_name"] == "Physics"
    assert [a["title"] for a in chosen["assignments_due"]] == ["Lab 2"]
    assert chosen["assignments_due"][0]["days_left"] == 1
    markers = [m for d in chosen["week"] for m in d["markers"]]
    assert {(m["kind"], m["title"]) for m in markers} == {("exam", "Physics midterm"), ("assignment", "Lab 2")}
    assert chosen["week"][0]["minutes_planned"] == 30 and chosen["week"][0]["tasks"] == 1

    other = user.get("/dashboard", params={"course": biology}).json()
    assert other["course"]["id"] == biology
    assert [w["material"] for w in other["weak_topics"]] == ["cells.pdf"]

    # someone else's (or an unknown) course id means "all courses", never that course's data
    stranger = make_user()
    foreign = make_subject(stranger, "Chemistry")
    fallback = user.get("/dashboard", params={"course": foreign}).json()
    assert fallback["course"] is None and fallback["scope"] == "all"
    assert fallback["overview"]["courses"] == 2


def test_activity_links_point_at_real_pages(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    subject = make_subject(user)
    chat = user.post("/conversations", json={}).json()
    add_attempt(user, subject, "cells.pdf", [1, 1])
    items = {i["kind"]: i for i in user.get("/dashboard").json()["activity"]}
    assert items["chat"]["href"] == f"/chat?c={chat['id']}"
    assert items["quiz"]["href"].startswith("/quizzes/attempt/") and items["quiz"]["detail"] == "100%"


def test_days_off_are_flagged_in_the_week(make_user) -> None:  # type: ignore[no-untyped-def]
    user = make_user()
    weekday = (today() + timedelta(days=2)).weekday()
    assert user.request("PUT", "/planner/preferences", json={"daily_minutes": 120, "days_off": [weekday]}).status_code == 200
    body = user.get("/dashboard").json()
    assert body["daily_minutes"] == 120
    assert [d["day_off"] for d in body["week"]].count(True) >= 1 and body["week"][2]["day_off"] is True
