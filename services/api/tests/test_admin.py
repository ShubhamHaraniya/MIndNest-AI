"""The admin screens, against a real database."""

import asyncio
import uuid
from typing import Any

import pytest
from mindnest_core import adminctl
from mindnest_core.db import make_engine, make_session_factory, user_session
from mindnest_core.settings import get_settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

NOTES = b"# Notes\n\nSome study notes.\n"
PASSWORD = "correct horse battery"


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


def as_app(user_id, query: str, **params: Any) -> Any:  # type: ignore[no-untyped-def]
    """Run a statement as the application role for one student (the way the API does)."""

    async def go() -> Any:
        engine = make_engine(get_settings().database_url)
        try:
            async with user_session(make_session_factory(engine), user_id) as session:
                result = await session.execute(text(query), params)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


@pytest.fixture
def admin(make_user):  # type: ignore[no-untyped-def]
    user = make_user("Admin Person")
    sql("UPDATE users SET is_admin = true WHERE id = :u", u=user.id)
    return user


def subject_with_file(user, name="notes.md", data=NOTES):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": "Biology"}).json()["id"]
    response = user.post(f"/subjects/{subject_id}/materials", files={"file": (name, data)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ------------------------------------------------------------------ who may come in


ROUTES = [
    ("get", "/admin/overview", None),
    ("get", "/admin/users", None),
    ("post", f"/admin/users/{uuid.uuid4()}/status", {"status": "suspended"}),
    ("get", "/admin/reports", None),
    ("post", f"/admin/reports/{uuid.uuid4()}/remove", {}),
    ("post", f"/admin/reports/{uuid.uuid4()}/dismiss", None),
    ("get", "/admin/security", None),
    ("get", "/admin/audit", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_only_admins_get_in(make_user, anon, method, path, body):  # type: ignore[no-untyped-def]
    student = make_user()
    kwargs = {"json": body} if body is not None else {}
    assert getattr(anon, method)(path, **kwargs).status_code == 401
    refused = getattr(student, method)(path, **kwargs)
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"


def test_the_me_endpoint_says_whether_the_student_is_an_admin(make_user, admin):  # type: ignore[no-untyped-def]
    assert admin.get("/auth/me").json()["is_admin"] is True
    assert make_user().get("/auth/me").json()["is_admin"] is False


def test_a_suspended_admin_has_no_admin_rights(admin):  # type: ignore[no-untyped-def]
    sql("UPDATE users SET status = 'suspended' WHERE id = :u", u=admin.id)
    assert admin.get("/admin/overview").status_code == 401


def test_the_application_cannot_make_anyone_an_admin(make_user):  # type: ignore[no-untyped-def]
    student = make_user()
    with pytest.raises(DBAPIError):
        as_app(student.id, "UPDATE users SET is_admin = true WHERE id = :u", u=student.id)
    with pytest.raises(DBAPIError):
        as_app(
            student.id,
            "INSERT INTO users (email, password_hash, display_name, is_admin) VALUES (:e, 'x', 'x', true)",
            e=f"{uuid.uuid4().hex}@mindnest-tests.dev",
        )
    assert sql("SELECT is_admin FROM users WHERE id = :u", u=student.id)[0][0] is False


def test_the_database_refuses_admin_functions_to_other_students(make_user):  # type: ignore[no-untyped-def]
    student = make_user()
    for call in (
        "SELECT app_admin_overview()",
        "SELECT * FROM app_admin_users('', 10, 0)",
        "SELECT * FROM app_admin_reports()",
        "SELECT * FROM app_admin_security(7)",
        "SELECT * FROM app_admin_audit(10)",
        "SELECT app_admin_set_status(gen_random_uuid(), 'suspended', '')",
        "SELECT app_admin_remove_item(gen_random_uuid(), '')",
    ):
        with pytest.raises(DBAPIError):
            as_app(student.id, call)
    with pytest.raises(DBAPIError):
        as_app(student.id, "SELECT count(*) FROM admin_audit_log")


def test_even_an_admin_cannot_read_a_students_files_or_chats(make_user, admin):  # type: ignore[no-untyped-def]
    student = make_user()
    subject_with_file(student)
    for table in ("materials", "subjects", "chunks", "conversations", "provider_keys", "quizzes", "assignments"):
        assert as_app(admin.id, f"SELECT count(*) FROM {table}")[0][0] == 0, table


# ------------------------------------------------------------------ overview and users


def test_the_overview_counts_what_is_happening(make_user, admin):  # type: ignore[no-untyped-def]
    before = admin.get("/admin/overview").json()["totals"]
    student = make_user()
    subject_with_file(student)
    after = admin.get("/admin/overview").json()
    totals = after["totals"]
    assert totals["users_total"] == before["users_total"] + 1
    assert totals["users_active"] == before["users_active"] + 1
    assert totals["signups_7d"] >= before["signups_7d"] + 1
    assert totals["materials"] == before["materials"] + 1
    assert totals["storage_bytes"] == before["storage_bytes"] + len(NOTES)
    assert totals["subjects"] == before["subjects"] + 1
    for key in ("groups", "shared_items", "reported_items", "ai_runs_7d", "tokens_7d", "security_events_7d"):
        assert key in totals
    series = after["series"]
    assert len(series) == 30 and series[-1]["signups"] >= 2
    assert len(admin.get("/admin/overview?days=7").json()["series"]) == 7
    assert admin.get("/admin/overview?days=500").status_code == 422


def test_the_user_list_shows_accounts_with_counts_and_no_secrets(make_user, admin):  # type: ignore[no-untyped-def]
    student = make_user("Zoya Findable")
    subject_with_file(student)
    found = admin.get("/admin/users", params={"q": "Zoya Findable"}).json()
    assert found["total"] == 1
    row = found["items"][0]
    assert row["email"] == student.email and row["status"] == "active" and row["is_admin"] is False
    assert (row["subjects"], row["materials"], row["storage_bytes"]) == (1, 1, len(NOTES))
    assert row["has_google"] is False and row["last_seen_at"] is not None
    assert "password" not in str(found).lower() and "hash" not in str(found).lower()
    assert admin.get("/admin/users", params={"q": student.email.upper()}).json()["total"] == 1


def test_search_text_is_taken_literally(make_user, admin):  # type: ignore[no-untyped-def]
    make_user("Percent Person")
    assert admin.get("/admin/users", params={"q": "%"}).json()["total"] == 0
    assert admin.get("/admin/users", params={"q": "_"}).json()["total"] == 0
    assert admin.get("/admin/users", params={"q": "x" * 101}).status_code == 422


def test_the_user_list_has_pages(make_user, admin):  # type: ignore[no-untyped-def]
    make_user(), make_user()
    first = admin.get("/admin/users", params={"limit": 1}).json()
    second = admin.get("/admin/users", params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] >= 3
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]


# ------------------------------------------------------------------ suspending


def test_suspending_signs_the_student_out_and_blocks_sign_in_until_reactivated(make_user, admin, anon):  # type: ignore[no-untyped-def]
    student = make_user()
    assert student.get("/auth/me").status_code == 200
    response = admin.post(f"/admin/users/{student.id}/status", json={"status": "suspended", "reason": "spam"})
    assert response.status_code == 200 and response.json() == {"status": "suspended"}
    assert student.get("/auth/me").status_code == 401
    login = anon.post("/auth/login", json={"email": student.email, "password": PASSWORD})
    assert login.status_code in (401, 403)
    listed = admin.get("/admin/users", params={"q": student.email}).json()["items"][0]
    assert listed["status"] == "suspended"
    assert admin.post(f"/admin/users/{student.id}/status", json={"status": "active"}).json() == {"status": "active"}
    assert anon.post("/auth/login", json={"email": student.email, "password": PASSWORD}).status_code == 200


def test_admins_cannot_suspend_themselves_or_each_other(make_user, admin):  # type: ignore[no-untyped-def]
    other_admin = make_user()
    sql("UPDATE users SET is_admin = true WHERE id = :u", u=other_admin.id)
    for target in (admin.id, other_admin.id):
        response = admin.post(f"/admin/users/{target}/status", json={"status": "suspended"})
        assert response.status_code == 409 and response.json()["code"] == "admin_account"
    assert other_admin.get("/auth/me").status_code == 200


def test_status_changes_are_validated(admin):  # type: ignore[no-untyped-def]
    assert admin.post(f"/admin/users/{uuid.uuid4()}/status", json={"status": "suspended"}).status_code == 404
    assert admin.post(f"/admin/users/{uuid.uuid4()}/status", json={"status": "deleted"}).status_code == 422
    assert admin.post(f"/admin/users/{uuid.uuid4()}/status", json={"status": "active", "reason": "x" * 301}).status_code == 422


def test_every_admin_change_is_in_the_audit_log(make_user, admin):  # type: ignore[no-untyped-def]
    student = make_user()
    admin.post(f"/admin/users/{student.id}/status", json={"status": "suspended", "reason": "sharing exam papers"})
    admin.post(f"/admin/users/{student.id}/status", json={"status": "active"})
    entries = admin.get("/admin/audit").json()
    mine = [e for e in entries if e["target_email"] == student.email]
    assert [e["action"] for e in mine[:2]] == ["activate_user", "suspend_user"]
    assert mine[1]["detail"]["reason"] == "sharing exam papers" and mine[0]["admin_name"] == "Admin Person"


# ------------------------------------------------------------------ reported files


def make_reported_file(make_user, reports=3, reason="copyright", note="from a textbook"):  # type: ignore[no-untyped-def]
    owner, sharer = make_user("Group Owner"), make_user("Careless Sharer")
    group = owner.post("/groups", json={"name": "Class"}).json()
    sharer.post("/groups/join", json={"code": group["join_code"]})
    material = subject_with_file(sharer)
    item = sharer.post(
        f"/groups/{group['id']}/items", json={"material_id": material, "confirm_rights": True}
    ).json()
    for index in range(reports):
        reporter = make_user(f"Reporter {index}")
        reporter.post("/groups/join", json={"code": group["join_code"]})
        reporter.post(f"/groups/{group['id']}/items/{item['id']}/report", json={"reason": reason, "note": note})
    return owner, sharer, group, item


def test_admins_see_reported_files_with_reasons_and_who_shared_them(make_user, admin):  # type: ignore[no-untyped-def]
    _, sharer, group, item = make_reported_file(make_user)
    rows = [r for r in admin.get("/admin/reports").json() if r["item_id"] == item["id"]]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "hidden" and row["reports"] == 3 and row["reasons"] == {"copyright": 3}
    assert row["notes"] == ["from a textbook"] * 3
    assert (row["group_name"], row["filename"], row["shared_by_email"]) == ("Class", "notes.md", sharer.email)


def test_dismissing_reports_restores_the_file(make_user, admin):  # type: ignore[no-untyped-def]
    owner, _, group, item = make_reported_file(make_user)
    assert admin.post(f"/admin/reports/{item['id']}/dismiss").status_code == 204
    assert all(r["item_id"] != item["id"] for r in admin.get("/admin/reports").json())
    assert owner.get(f"/groups/{group['id']}/items").json()[0]["status"] == "active"
    assert admin.post(f"/admin/reports/{item['id']}/dismiss").status_code == 204  # nothing left to clear, still fine


def test_removing_a_reported_file_deletes_it_and_its_stored_copy(make_user, admin, storage):  # type: ignore[no-untyped-def]
    owner, _, group, item = make_reported_file(make_user)
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert key in storage.objects
    assert admin.post(f"/admin/reports/{item['id']}/remove", json={"reason": "copyright claim"}).status_code == 204
    assert key not in storage.objects
    assert owner.get(f"/groups/{group['id']}/items").json() == []
    assert admin.post(f"/admin/reports/{item['id']}/remove", json={}).status_code == 404
    last = admin.get("/admin/audit").json()[0]
    assert last["action"] == "remove_shared_file" and last["detail"]["reason"] == "copyright claim"


# ------------------------------------------------------------------ security summary


def test_the_security_summary_counts_events_without_their_text(make_user, admin):  # type: ignore[no-untyped-def]
    one, two = make_user(), make_user()
    for who in (one, one, two):
        sql(
            "INSERT INTO security_events (user_id, kind, source, detail) "
            "VALUES (:u, 'injection_in_source', 'notes.pdf', '{\"phrases\": 2}')",
            u=who.id,
        )
    rows = {r["kind"]: r for r in admin.get("/admin/security?days=1").json()}
    assert rows["injection_in_source"]["events"] >= 3 and rows["injection_in_source"]["students"] >= 2
    assert set(rows["injection_in_source"]) == {"kind", "events", "students"}
    assert admin.get("/admin/security?days=0").status_code == 422


# ------------------------------------------------------------------ the command line


async def run_ctl(email: str, value: bool) -> str:
    engine = make_engine(get_settings().migration_database_url)
    try:
        return await adminctl.set_admin(engine, email, value)
    finally:
        await engine.dispose()


def test_the_command_line_grants_and_revokes_admin_rights(make_user):  # type: ignore[no-untyped-def]
    student = make_user()
    assert asyncio.run(run_ctl(student.email, True)) == "unverified"
    sql("UPDATE users SET email_verified_at = now() WHERE id = :u", u=student.id)
    assert student.get("/admin/overview").status_code == 403
    assert asyncio.run(run_ctl(student.email.upper(), True)) == "ok"
    assert student.get("/admin/overview").status_code == 200
    assert asyncio.run(run_ctl(student.email, False)) == "ok"
    assert student.get("/admin/overview").status_code == 403
    assert asyncio.run(run_ctl("nobody@mindnest-tests.dev", True)) == "not_found"
    sql("UPDATE users SET status = 'suspended' WHERE id = :u", u=student.id)
    assert asyncio.run(run_ctl(student.email, True)) == "inactive"


def test_the_command_line_leaves_a_record(make_user):  # type: ignore[no-untyped-def]
    student = make_user()
    sql("UPDATE users SET email_verified_at = now() WHERE id = :u", u=student.id)
    asyncio.run(run_ctl(student.email, True))
    rows = sql("SELECT action FROM admin_audit_log WHERE target_user = :u", u=student.id)
    assert [r[0] for r in rows] == ["grant_admin"]
