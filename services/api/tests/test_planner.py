"""Exams, the study planner and the calendar, against a real database."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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


def today():  # type: ignore[no-untyped-def]
    return datetime.now(UTC).date()


def day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def subject(user, name="Biology"):  # type: ignore[no-untyped-def]
    return user.post("/subjects", json={"name": name}).json()["id"]


def add_exam(user, offset=10, **extra):  # type: ignore[no-untyped-def]
    response = user.post("/exams", json={"title": "Midterm", "exam_on": day(offset), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def give_cards(user, subject_id, count, due_offset=0):  # type: ignore[no-untyped-def]
    for _ in range(count):
        sql(
            "INSERT INTO revision_cards (user_id, subject_id, origin_question_id, qtype, prompt, answer, due_at) "
            "VALUES (:u, :s, :o, 'short', 'Q?', 'A', now() + make_interval(days => :d))",
            u=user.id, s=subject_id, o=str(uuid.uuid4()), d=due_offset,
        )


def give_quiz_results(user, subject_id, filename, scores):  # type: ignore[no-untyped-def]
    quiz = sql(
        "INSERT INTO quizzes (user_id, subject_id, title, status) VALUES (:u, :s, 'Q', 'ready') RETURNING id",
        u=user.id, s=subject_id,
    )[0][0]
    attempt = sql(
        "INSERT INTO quiz_attempts (quiz_id, user_id, status) VALUES (:q, :u, 'completed') RETURNING id",
        q=quiz, u=user.id,
    )[0][0]
    for position, score in enumerate(scores, start=1):
        question = sql(
            "INSERT INTO quiz_questions (quiz_id, user_id, position, qtype, prompt, answer, source) "
            "VALUES (:q, :u, :p, 'short', 'Q?', 'A', CAST(:src AS jsonb)) RETURNING id",
            q=quiz, u=user.id, p=position, src=json.dumps({"filename": filename}),
        )[0][0]
        sql(
            "INSERT INTO quiz_answers (attempt_id, question_id, user_id, response, score) "
            "VALUES (:a, :q, :u, 'x', :s)",
            a=attempt, q=question, u=user.id, s=score,
        )


def tasks(user, first=0, last=20):  # type: ignore[no-untyped-def]
    return user.get("/planner/tasks", params={"from": day(first), "to": day(last)}).json()["items"]


# ------------------------------------------------------------------ preferences and exams


def test_preferences_have_defaults_and_can_be_changed(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get("/planner/preferences").json() == {"daily_minutes": 90, "days_off": []}
    saved = user.request("PUT", "/planner/preferences", json={"daily_minutes": 120, "days_off": [6, 5, 5]})
    assert saved.json() == {"daily_minutes": 120, "days_off": [5, 6]}
    assert user.get("/planner/preferences").json()["daily_minutes"] == 120
    for bad in ({"daily_minutes": 5, "days_off": []}, {"daily_minutes": 600, "days_off": []},
                {"daily_minutes": 90, "days_off": [7]}, {"daily_minutes": 90, "days_off": [0, 1, 2, 3, 4, 5, 6]}):
        assert user.request("PUT", "/planner/preferences", json=bad).status_code == 422


def test_an_exam_can_be_added_changed_and_removed(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    exam = add_exam(user, 10, subject_id=subject_id)
    assert exam["days_left"] == 10 and exam["subject_name"] == "Biology"
    moved = user.patch(f"/exams/{exam['id']}", json={"exam_on": day(12), "subject_id": None}).json()
    assert moved["days_left"] == 12 and moved["subject_id"] is None
    assert [e["id"] for e in user.get("/exams").json()] == [exam["id"]]
    assert user.patch(f"/exams/{exam['id']}", json={"title": None}).status_code == 422
    assert user.delete(f"/exams/{exam['id']}").status_code == 204
    assert user.delete(f"/exams/{exam['id']}").status_code == 404


def test_bad_exam_input_and_other_peoples_exams(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    assert owner.post("/exams", json={"title": " ", "exam_on": day(3)}).status_code == 422
    assert owner.post("/exams", json={"title": "x", "exam_on": "soon"}).status_code == 422
    assert owner.post("/exams", json={"title": "x", "exam_on": day(3), "subject_id": str(uuid.uuid4())}).status_code == 404
    exam = add_exam(owner)
    assert other.get("/exams").json() == []
    assert other.patch(f"/exams/{exam['id']}", json={"title": "mine now"}).status_code == 404
    assert other.delete(f"/exams/{exam['id']}").status_code == 404


# ------------------------------------------------------------------ generating a plan


def test_a_plan_is_made_from_exams_assignments_and_due_cards(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    add_exam(user, 10, subject_id=subject_id)
    due = (datetime.now(UTC) + timedelta(days=6)).isoformat()
    user.post("/assignments", json={"title": "Essay", "brief": "Write.", "subject_id": subject_id, "due_at": due})
    give_cards(user, subject_id, 6)

    result = user.post("/planner/generate", json={}).json()
    assert result["created"] > 0 and result["notice"] is None
    items = tasks(user)
    assert len(items) == result["created"]
    templates = {t["template"] for t in items}
    assert {"exam_final", "assignment_write", "assignment_review", "cards_due"} <= templates
    assert all(t["source"] == "plan" and t["status"] == "todo" for t in items)
    final = next(t for t in items if t["template"] == "exam_final")
    assert final["planned_for"] == day(9) and final["title"] == "Final revision: Biology"
    cards = next(t for t in items if t["template"] == "cards_due")
    assert cards["planned_for"] == day(0) and cards["params"] == {"count": 6}
    assert all(t["planned_for"] < day(10) for t in items if t["kind"] == "revise" and t["exam_id"])


def test_generating_again_replaces_the_plan_but_keeps_finished_and_own_tasks(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    add_exam(user, 8, subject_id=subject_id)
    user.post("/planner/generate", json={})
    first = tasks(user)
    finished = first[0]
    assert user.patch(f"/planner/tasks/{finished['id']}", json={"status": "done"}).json()["status"] == "done"
    mine = user.post("/planner/tasks", json={"title": "Buy a lab coat", "planned_for": day(1), "minutes": 15}).json()
    assert mine["source"] == "manual" and mine["kind"] == "custom"

    again = user.post("/planner/generate", json={"days": 14}).json()
    now = tasks(user)
    ids = {t["id"] for t in now}
    assert finished["id"] in ids and mine["id"] in ids  # kept
    assert len(now) == again["created"] + 2  # the finished one and the student's own
    assert len([t for t in now if t["source"] == "plan" and t["status"] == "todo"]) == again["created"]


def test_nothing_to_plan_says_so(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    result = user.post("/planner/generate", json={}).json()
    assert result == {
        "created": 0, "first_day": day(0), "last_day": day(13), "notice": "nothing_to_plan",
        "kept": 0, "already_handled": 0,
    }


def test_the_plan_respects_days_off_and_daily_time(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_exam(user, 12)
    off = (today() + timedelta(days=3)).weekday()
    user.request("PUT", "/planner/preferences", json={"daily_minutes": 60, "days_off": [off]})
    user.post("/planner/generate", json={})
    items = tasks(user)
    assert items and all(datetime.fromisoformat(t["planned_for"]).weekday() != off for t in items)
    per_day: dict[str, int] = {}
    for t in items:
        per_day[t["planned_for"]] = per_day.get(t["planned_for"], 0) + t["minutes"]
    assert max(per_day.values()) <= 60


def test_weak_material_from_quizzes_is_revised_first(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    add_exam(user, 12, subject_id=subject_id)
    give_quiz_results(user, subject_id, "chapter2.pdf", [0, 0, 0.5, 0])
    give_quiz_results(user, subject_id, "chapter1.pdf", [1, 1, 1, 1])
    user.post("/planner/generate", json={})
    weak = [t for t in tasks(user) if t["template"] == "exam_weak"]
    assert [t["params"]["name"] for t in weak] == ["chapter2.pdf"]
    assert weak[0]["params"]["percent"] == 12 or weak[0]["params"]["percent"] == 13


def test_cards_already_overdue_are_planned_for_today(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    give_cards(user, subject_id, 4, due_offset=-3)
    user.post("/planner/generate", json={})
    (card,) = tasks(user)
    assert card["template"] == "cards_due" and card["planned_for"] == day(0)


# ------------------------------------------------------------------ working with tasks


def test_tasks_can_be_ticked_skipped_moved_and_deleted(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    made = user.post("/planner/tasks", json={"title": "Read chapter 3", "planned_for": day(2)}).json()
    assert made["minutes"] == 30 and made["status"] == "todo"
    done = user.patch(f"/planner/tasks/{made['id']}", json={"status": "done"}).json()
    assert done["status"] == "done"
    assert sql("SELECT completed_at FROM study_tasks WHERE id = :i", i=made["id"])[0][0] is not None
    back = user.patch(f"/planner/tasks/{made['id']}", json={"status": "todo", "planned_for": day(3), "minutes": 45}).json()
    assert back["planned_for"] == day(3) and back["minutes"] == 45
    assert sql("SELECT completed_at FROM study_tasks WHERE id = :i", i=made["id"])[0][0] is None
    renamed = user.patch(f"/planner/tasks/{made['id']}", json={"title": "Read chapter 4"}).json()
    assert renamed["title"] == "Read chapter 4"
    assert user.delete(f"/planner/tasks/{made['id']}").status_code == 204
    assert user.delete(f"/planner/tasks/{made['id']}").status_code == 404


def test_a_planned_task_keeps_its_title_and_bad_task_input_is_refused(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_exam(user, 6)
    user.post("/planner/generate", json={})
    planned = tasks(user)[0]
    refused = user.patch(f"/planner/tasks/{planned['id']}", json={"title": "renamed"})
    assert refused.status_code == 409
    # "skipped" is the old word for cancelled and is stored as cancelled.
    assert user.patch(f"/planner/tasks/{planned['id']}", json={"status": "skipped"}).json()["status"] == "cancelled"
    assert user.post("/planner/tasks", json={"title": "x", "planned_for": day(1), "minutes": 2}).status_code == 422
    assert user.post("/planner/tasks", json={"title": "x", "planned_for": "tomorrow"}).status_code == 422
    assert user.patch(f"/planner/tasks/{planned['id']}", json={"status": "finished"}).status_code == 422


def test_one_student_cannot_see_or_change_anothers_tasks(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    made = owner.post("/planner/tasks", json={"title": "Private", "planned_for": day(1)}).json()
    assert tasks(other) == []
    assert other.patch(f"/planner/tasks/{made['id']}", json={"status": "done"}).status_code == 404
    assert other.delete(f"/planner/tasks/{made['id']}").status_code == 404
    other.post("/planner/generate", json={})
    assert [t["id"] for t in tasks(owner)] == [made["id"]]


def test_the_task_range_is_limited(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    response = user.get("/planner/tasks", params={"from": day(0), "to": day(400)})
    assert response.status_code == 422
    assert user.get("/planner/tasks", params={"from": day(5), "to": day(1)}).status_code == 422


# ------------------------------------------------------------------ the calendar


def test_the_calendar_merges_deadlines_exams_tasks_and_revision(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    add_exam(user, 5, subject_id=subject_id)
    due = (datetime.now(UTC) + timedelta(days=2)).replace(hour=12).isoformat()
    user.post("/assignments", json={"title": "Essay", "brief": "x", "due_at": due})
    user.post("/planner/tasks", json={"title": "Read", "planned_for": day(1)})
    give_cards(user, subject_id, 3, due_offset=0)
    give_cards(user, subject_id, 2, due_offset=-4)  # overdue: shown today

    response = user.get("/calendar", params={"from": day(0), "to": day(7)}).json()
    assert response["today"] == day(0)
    kinds = [(e["kind"], e["day"]) for e in response["events"]]
    assert ("exam", day(5)) in kinds and ("assignment", day(2)) in kinds and ("task", day(1)) in kinds
    revision = [e for e in response["events"] if e["kind"] == "revision"]
    assert len(revision) == 1 and revision[0]["day"] == day(0) and revision[0]["count"] == 5
    assert [e["day"] for e in response["events"]] == sorted(e["day"] for e in response["events"])


def test_the_calendar_only_returns_the_asked_days_and_limits_the_range(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_exam(user, 5)
    add_exam(user, 40, title="Final")
    assert [e["kind"] for e in user.get("/calendar", params={"from": day(30), "to": day(45)}).json()["events"]] == ["exam"]
    assert user.get("/calendar", params={"from": day(0), "to": day(100)}).status_code == 422
    assert user.get("/calendar", params={"from": day(0)}).status_code == 422


def test_dates_follow_the_students_time_zone(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.patch("/me", json={"timezone": "Pacific/Kiritimati"}).status_code == 200  # UTC+14
    from zoneinfo import ZoneInfo

    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    assert user.get("/planner/tasks").json()["today"] == expected


# ------------------------------------------------------------------ states, overload and regeneration


def test_a_task_can_be_cancelled_and_restored_and_says_what_state_it_is_in(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    late = user.post("/planner/tasks", json={"title": "Late", "planned_for": day(-2)}).json()
    soon = user.post("/planner/tasks", json={"title": "Soon", "planned_for": day(1)}).json()
    assert (late["state"], soon["state"]) == ("overdue", "pending")
    cancelled = user.patch(f"/planner/tasks/{late['id']}", json={"status": "cancelled"}).json()
    assert cancelled["status"] == "cancelled" and cancelled["state"] == "cancelled"
    done = user.patch(f"/planner/tasks/{soon['id']}", json={"status": "done"}).json()
    assert done["state"] == "completed"
    restored = user.patch(f"/planner/tasks/{late['id']}", json={"status": "todo"}).json()
    assert restored["state"] == "overdue"
    assert sql("SELECT status FROM study_tasks WHERE id = :i", i=done["id"])[0][0] == "done"


def test_a_manual_task_can_change_course_but_a_planned_one_cannot(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = subject(user)
    mine = user.post("/planner/tasks", json={"title": "Read", "planned_for": day(1)}).json()
    moved = user.patch(f"/planner/tasks/{mine['id']}", json={"subject_id": subject_id}).json()
    assert moved["subject_id"] == subject_id and moved["subject_name"] == "Biology"
    assert user.patch(f"/planner/tasks/{mine['id']}", json={"subject_id": str(uuid.uuid4())}).status_code == 404
    add_exam(user, 6)
    user.post("/planner/generate", json={})
    planned = next(t for t in tasks(user) if t["source"] == "plan")
    assert user.patch(f"/planner/tasks/{planned['id']}", json={"subject_id": subject_id}).status_code == 409


def test_a_day_with_too_much_is_flagged_with_a_lighter_day_to_move_to(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/planner/preferences", json={"daily_minutes": 60, "days_off": []})
    for _ in range(2):
        user.post("/planner/tasks", json={"title": "Read", "planned_for": day(1), "minutes": 40})
    response = user.get("/planner/tasks", params={"from": day(0), "to": day(13)}).json()
    assert response["daily_minutes"] == 60 and response["days_off"] == []
    (flag,) = response["overload"]
    assert flag["day"] == day(1) and flag["minutes"] == 80 and flag["limit"] == 60 and flag["excess"] == 20
    assert flag["day_off"] is False and flag["suggested"] in (day(0), day(2))


def test_cancelled_tasks_do_not_count_towards_the_load(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/planner/preferences", json={"daily_minutes": 60, "days_off": []})
    first = user.post("/planner/tasks", json={"title": "A", "planned_for": day(1), "minutes": 40}).json()
    user.post("/planner/tasks", json={"title": "B", "planned_for": day(1), "minutes": 40})
    assert len(user.get("/planner/tasks", params={"from": day(0), "to": day(13)}).json()["overload"]) == 1
    user.patch(f"/planner/tasks/{first['id']}", json={"status": "cancelled"})
    assert user.get("/planner/tasks", params={"from": day(0), "to": day(13)}).json()["overload"] == []


def test_work_on_a_day_off_is_flagged(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    off = (today() + timedelta(days=2)).weekday()
    user.request("PUT", "/planner/preferences", json={"daily_minutes": 120, "days_off": [off]})
    user.post("/planner/tasks", json={"title": "Sunday cram", "planned_for": day(2), "minutes": 30})
    (flag,) = user.get("/planner/tasks", params={"from": day(0), "to": day(13)}).json()["overload"]
    assert flag["day"] == day(2) and flag["day_off"] is True and flag["excess"] == 30
    assert flag["suggested"] is not None
    assert datetime.fromisoformat(flag["suggested"]).weekday() != off


def test_a_cancelled_planner_task_stays_cancelled_and_is_not_planned_again(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    exam = add_exam(user, 10)
    user.post("/planner/generate", json={})
    final = next(t for t in tasks(user) if t["template"] == "exam_final")
    assert user.patch(f"/planner/tasks/{final['id']}", json={"status": "cancelled"}).json()["state"] == "cancelled"

    again = user.post("/planner/generate", json={}).json()
    now = tasks(user)
    assert again["already_handled"] >= 1
    kept = next(t for t in now if t["id"] == final["id"])
    assert kept["status"] == "cancelled"
    assert [t for t in now if t["template"] == "exam_final" and t["exam_id"] == exam["id"]] == [kept]


def test_nothing_new_to_plan_is_reported_as_up_to_date(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_exam(user, 1)  # one revision session, today
    user.post("/planner/generate", json={})
    (only,) = tasks(user)
    user.patch(f"/planner/tasks/{only['id']}", json={"status": "cancelled"})
    result = user.post("/planner/generate", json={}).json()
    assert result["created"] == 0 and result["notice"] == "up_to_date" and result["already_handled"] == 1
    assert [t["status"] for t in tasks(user)] == ["cancelled"]


def test_moving_a_planner_task_pins_it_so_the_plan_keeps_it(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    add_exam(user, 12)
    user.post("/planner/generate", json={})
    before = tasks(user)
    revise = [t for t in before if t["template"] == "exam_revise"]
    target = revise[0]
    assert target["pinned"] is False
    new_day = day(1) if target["planned_for"] != day(1) else day(2)
    moved = user.patch(f"/planner/tasks/{target['id']}", json={"planned_for": new_day}).json()
    assert moved["pinned"] is True and moved["planned_for"] == new_day and moved["status"] == "todo"

    user.post("/planner/generate", json={})
    after = tasks(user)
    same = next(t for t in after if t["id"] == target["id"])
    assert same["planned_for"] == new_day and same["pinned"] is True
    # The pinned one counts as one of the sessions: no extra session was made for it.
    assert len([t for t in after if t["template"] == "exam_revise"]) == len(revise)
