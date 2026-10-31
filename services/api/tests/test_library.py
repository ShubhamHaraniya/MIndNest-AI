"""The Materials Library, against a real database: who sees what, review, reports and takedown."""

import asyncio
import uuid
from typing import Any

import pytest
from mindnest_core.db import make_engine
from mindnest_core.librarylogic import HOLD_AT_REPORTS
from mindnest_core.settings import get_settings
from sqlalchemy import text

NOTES = b"# Processes\n\nA process is a program in execution. Each process has its own address space.\n"


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


@pytest.fixture
def admin(make_user):  # type: ignore[no-untyped-def]
    user = make_user("Moderator")
    sql("UPDATE users SET is_admin = true WHERE id = :u", u=user.id)
    return user


# Every test gets institution names of its own, because the database is shared by the whole run:
# without this, "IIT Delhi" from one test would be the same college as "IIT Delhi" in another.
SUFFIX = ""


@pytest.fixture(autouse=True)
def _own_institutions():  # type: ignore[no-untyped-def]
    global SUFFIX
    SUFFIX = uuid.uuid4().hex[:8]
    yield


def student(make_user, name, institution=""):  # type: ignore[no-untyped-def]
    user = make_user(name)
    if institution:
        response = user.patch("/me", json={"institution_name": f"{institution} {SUFFIX}"})
        assert response.status_code == 200
    return user


def material(user, name="notes.md", data=NOTES, kind="note", subject_name="Operating Systems"):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": subject_name}).json()["id"]
    response = user.post(
        f"/subjects/{subject_id}/materials", files={"file": (name, data)}, data={"kind": kind}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], subject_id


def publish(user, material_id, **extra):  # type: ignore[no-untyped-def]
    body = {"material_id": material_id, "confirm_rights": True, **extra}
    return user.post("/library", json=body)


def ids(user, scope):  # type: ignore[no-untyped-def]
    response = user.get("/library", params={"scope": scope})
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# ------------------------------------------------------------------ the institution


def test_institution_is_saved_with_tidy_spacing_and_can_be_cleared(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get("/auth/me").json()["institution_name"] == ""
    assert user.patch("/me", json={"institution_name": "  IIT   Delhi "}).json()["institution_name"] == "IIT Delhi"
    assert user.patch("/me", json={"institution_name": ""}).json()["institution_name"] == ""
    assert user.patch("/me", json={"institution_name": "x" * 121}).status_code == 422
    assert user.patch("/me", json={"institution_name": None}).status_code == 422


def test_suggestions_only_list_names_two_students_share(make_user):  # type: ignore[no-untyped-def]
    unique = "Zephyr Institute of Testing"
    first = student(make_user, "One", unique)
    assert first.get("/library/institutions", params={"q": "zephyr"}).json() == []
    student(make_user, "Two", "  zephyr   institute of testing")
    names = first.get("/library/institutions", params={"q": "zephyr"}).json()
    assert len(names) == 1 and names[0]["students"] == 2


# ------------------------------------------------------------------ who sees what


def test_a_private_item_is_never_visible_to_anyone_else(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="private").json()
    assert item["status"] == "draft" and item["visibility"] == "private" and item["mine"] is True
    assert ids(alice, "mine") == [item["id"]]
    for scope in ("college", "others", "global"):
        assert item["id"] not in ids(bob, scope)
        assert item["id"] not in ids(alice, scope)
    assert bob.get(f"/library/{item['id']}").status_code == 404
    assert bob.get(f"/library/{item['id']}/file").status_code == 404


def test_institution_only_reaches_the_same_college_however_it_was_typed(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "  iit   DELHI ")
    carol = student(make_user, "Carol", "NIT Surat")
    dan = student(make_user, "Dan")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="institution", title="OS notes").json()
    assert item["status"] == "published" and item["institution"].startswith("IIT Delhi ")

    assert ids(bob, "college") == [item["id"]]
    for outsider in (carol, dan):
        assert ids(outsider, "college") == []
        assert item["id"] not in ids(outsider, "others")
        assert item["id"] not in ids(outsider, "global")
        assert outsider.get(f"/library/{item['id']}").status_code == 404
        assert outsider.get(f"/library/{item['id']}/file").status_code == 404
    assert bob.get(f"/library/{item['id']}/file").content == NOTES
    # An institution-only file does not appear under "other colleges" for the same college either.
    assert item["id"] not in ids(bob, "others")


def test_changing_institution_changes_what_college_means(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "NIT Surat")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="institution").json()
    assert ids(bob, "college") == []
    bob.patch("/me", json={"institution_name": f"iit delhi {SUFFIX}"})
    assert ids(bob, "college") == [item["id"]]
    bob.patch("/me", json={"institution_name": ""})
    page = bob.get("/library", params={"scope": "college"}).json()
    assert page["items"] == [] and page["my_institution"] == ""


def test_sharing_needs_rights_confirmation_an_institution_and_not_assignments(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice")
    material_id, _ = material(alice)
    no_institution = publish(alice, material_id, visibility="institution")
    assert no_institution.status_code == 422 and no_institution.json()["code"] == "institution_required"
    alice.patch("/me", json={"institution_name": "IIT Delhi"})
    unconfirmed = alice.post(
        "/library", json={"material_id": material_id, "visibility": "institution", "confirm_rights": False}
    )
    assert unconfirmed.status_code == 422 and unconfirmed.json()["code"] == "confirm_rights"
    work, _ = material(alice, "work.md", kind="assignment", subject_name="Maths")
    blocked = publish(alice, work, visibility="private")
    assert blocked.status_code == 422 and blocked.json()["code"] == "assignment_not_shareable"
    assert publish(alice, material_id, visibility="institution").status_code == 201
    assert publish(alice, material_id, visibility="institution").status_code == 409


def test_someone_elses_material_cannot_be_published(make_user):  # type: ignore[no-untyped-def]
    alice, mallory = student(make_user, "Alice", "IIT Delhi"), student(make_user, "Mallory", "IIT Delhi")
    material_id, _ = material(alice)
    assert publish(mallory, material_id, visibility="institution").status_code == 404


# ------------------------------------------------------------------ public items and review


def test_public_items_wait_for_review_and_then_reach_other_colleges_and_global(make_user, admin):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "NIT Surat")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="public", rights="open_licence").json()
    assert item["status"] == "pending_review"
    for scope in ("college", "others", "global"):
        assert item["id"] not in ids(bob, scope)
    queue = admin.get("/admin/library").json()
    assert item["id"] in [row["id"] for row in queue]

    assert admin.post(f"/admin/library/{item['id']}/approve", json={}).status_code == 204
    assert item["id"] in ids(bob, "others")
    assert item["id"] in ids(bob, "global")
    assert ids(alice, "college") == [item["id"]]
    assert item["id"] not in ids(alice, "others")
    assert alice.get(f"/library/{item['id']}").json()["status"] == "published"

    # Editing a public item sends it back for review, so a file cannot be swapped after approval.
    edited = alice.patch(f"/library/{item['id']}", json={"description": "Chapter 2 only"}).json()
    assert edited["status"] == "pending_review"
    assert item["id"] not in ids(bob, "others")


def test_global_is_only_openly_licensed_public_items(make_user, admin):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "NIT Surat")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="public", rights="own_work").json()
    admin.post(f"/admin/library/{item['id']}/approve", json={})
    assert item["id"] in ids(bob, "others")
    assert item["id"] not in ids(bob, "global")


def test_a_rejected_item_shows_the_reason_to_its_owner_only_and_can_be_resubmitted(make_user, admin):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "NIT Surat")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="public").json()
    admin.post(f"/admin/library/{item['id']}/reject", json={"note": "Please add the author"})
    mine = alice.get(f"/library/{item['id']}").json()
    assert mine["status"] == "rejected" and mine["review_note"] == "Please add the author"
    assert bob.get(f"/library/{item['id']}").status_code == 404
    again = alice.patch(f"/library/{item['id']}", json={"author": "A. Teacher"}).json()
    assert again["status"] == "pending_review"


def test_only_administrators_can_moderate(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="public").json()
    assert alice.get("/admin/library").status_code == 403
    for action in ("approve", "reject", "takedown"):
        assert alice.post(f"/admin/library/{item['id']}/{action}", json={}).status_code == 403
    assert alice.get(f"/library/{item['id']}").json()["status"] == "pending_review"


def test_the_app_role_cannot_publish_a_public_item_by_itself(make_user):  # type: ignore[no-untyped-def]
    """Row-level security, not just the API, keeps a public item in review."""
    alice = student(make_user, "Alice", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="public").json()
    from mindnest_core.db import make_session_factory, user_session
    from sqlalchemy.exc import DBAPIError

    async def try_update() -> None:
        engine = make_engine(get_settings().database_url)
        try:
            import uuid

            async with user_session(make_session_factory(engine), uuid.UUID(alice.id)) as session:
                await session.execute(
                    text("UPDATE library_items SET status = 'published' WHERE id = :i"), {"i": item["id"]}
                )
        finally:
            await engine.dispose()

    with pytest.raises(DBAPIError):
        asyncio.run(try_update())
    assert alice.get(f"/library/{item['id']}").json()["status"] == "pending_review"


# ------------------------------------------------------------------ reports


def test_reports_hold_an_item_until_a_moderator_decides(make_user, admin):  # type: ignore[no-untyped-def]
    owner = student(make_user, "Owner", "IIT Delhi")
    material_id, _ = material(owner)
    item = publish(owner, material_id, visibility="institution").json()
    readers = [student(make_user, f"Reader {n}", "IIT Delhi") for n in range(HOLD_AT_REPORTS)]
    assert owner.post(f"/library/{item['id']}/report", json={"reason": "other"}).status_code == 409

    for number, reader in enumerate(readers, start=1):
        response = reader.post(f"/library/{item['id']}/report", json={"reason": "copyright", "note": "not theirs"})
        assert response.status_code == 200
        assert response.json()["held"] is (number == HOLD_AT_REPORTS)
    # Once held, the item disappears for everyone but its owner.
    assert readers[0].get(f"/library/{item['id']}").status_code == 404
    assert ids(readers[1], "college") == []

    held = owner.get(f"/library/{item['id']}").json()
    assert held["status"] == "held"
    assert owner.patch(f"/library/{item['id']}", json={"title": "New title"}).status_code == 409
    row = next(r for r in admin.get("/admin/library").json() if r["id"] == item["id"])
    assert row["reports"] == HOLD_AT_REPORTS and "copyright" in row["reasons"]

    admin.post(f"/admin/library/{item['id']}/approve", json={})
    assert ids(readers[1], "college") == [item["id"]]
    assert next((r for r in admin.get("/admin/library").json() if r["id"] == item["id"]), None) is None


def test_the_reported_flag_follows_the_reporter(make_user):  # type: ignore[no-untyped-def]
    owner = student(make_user, "Owner", "IIT Delhi")
    reader = student(make_user, "Reader", "IIT Delhi")
    material_id, _ = material(owner)
    item = publish(owner, material_id, visibility="institution").json()
    assert reader.get(f"/library/{item['id']}").json()["reported_by_me"] is False
    reader.post(f"/library/{item['id']}/report", json={"reason": "wrong_content"})
    assert reader.get(f"/library/{item['id']}").json()["reported_by_me"] is True
    assert owner.get(f"/library/{item['id']}").json()["reported_by_me"] is False


# ------------------------------------------------------------------ copies, withdrawal, takedown


def test_a_student_can_add_a_library_file_to_their_own_course(make_user, ingest):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="institution").json()
    subject_id = bob.post("/subjects", json={"name": "OS"}).json()["id"]
    added = bob.post(f"/library/{item['id']}/add", json={"subject_id": subject_id})
    assert added.status_code == 201, added.text
    copy = bob.get(f"/materials/{added.json()['material_id']}").json()
    assert copy["filename"] == "notes.md" and copy["kind"] == "note"
    ingest(copy["id"], bob.id)
    assert bob.get(f"/materials/{copy['id']}").json()["chunk_count"] > 0
    # Somebody else's subject is not a destination.
    carol = student(make_user, "Carol", "IIT Delhi")
    assert carol.post(f"/library/{item['id']}/add", json={"subject_id": subject_id}).status_code == 404


def test_withdrawing_removes_the_item_but_not_copies_students_already_added(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="institution").json()
    subject_id = bob.post("/subjects", json={"name": "OS"}).json()["id"]
    copy_id = bob.post(f"/library/{item['id']}/add", json={"subject_id": subject_id}).json()["material_id"]
    assert alice.delete(f"/library/{item['id']}").status_code == 204
    assert ids(bob, "college") == []
    assert bob.get(f"/library/{item['id']}").status_code == 404
    assert bob.get(f"/materials/{copy_id}").status_code == 200
    assert bob.delete(f"/library/{item['id']}").status_code == 404


def test_a_takedown_pulls_copies_out_of_the_retrieval_index(make_user, admin, ingest):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    material_id, _ = material(alice)
    item = publish(alice, material_id, visibility="institution").json()
    subject_id = bob.post("/subjects", json={"name": "OS"}).json()["id"]
    copy_id = bob.post(f"/library/{item['id']}/add", json={"subject_id": subject_id}).json()["material_id"]
    ingest(copy_id, bob.id)
    assert sql("SELECT count(*) FROM chunks WHERE material_id = :m", m=copy_id)[0][0] > 0

    assert admin.post(f"/admin/library/{item['id']}/takedown", json={"note": "copyright claim"}).status_code == 204

    assert sql("SELECT count(*) FROM chunks WHERE material_id = :m", m=copy_id)[0][0] == 0
    assert bob.get(f"/materials/{copy_id}").status_code == 404
    assert ids(bob, "college") == []
    assert bob.get(f"/library/{item['id']}/file").status_code == 404
    mine = alice.get(f"/library/{item['id']}").json()
    assert mine["status"] == "taken_down" and mine["review_note"] == "copyright claim"
    assert alice.patch(f"/library/{item['id']}", json={"title": "Again"}).status_code == 409
    assert alice.get(f"/library/{item['id']}/file").status_code == 404
    audit = sql("SELECT action FROM admin_audit_log WHERE action = 'library_takedown' AND target_user = :u", u=alice.id)
    assert len(audit) == 1


def test_a_private_upload_is_never_in_anyone_elses_search(make_user):  # type: ignore[no-untyped-def]
    """Publishing to the library does not touch the owner's course index, and a private item has no
    audience at all."""
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    material_id, _ = material(alice)
    publish(alice, material_id, visibility="private")
    response = bob.get("/library", params={"scope": "college", "q": "process"})
    assert response.json()["items"] == []
    assert bob.get("/library", params={"scope": "mine", "q": "process"}).json()["items"] == []


# ------------------------------------------------------------------ filters


def test_filters_narrow_a_tab_and_facets_list_only_what_is_there(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    bob = student(make_user, "Bob", "IIT Delhi")
    first, _ = material(alice, "os.md", subject_name="Operating Systems")
    second, _ = material(alice, "db.md", data=b"# Joins\n\nA join combines rows.\n", subject_name="Databases")
    a = publish(
        alice, first, visibility="institution", title="Scheduling notes", topic="Scheduling",
        semester="4", academic_year="2025-26", doc_type="notes",
    ).json()
    b = publish(
        alice, second, visibility="institution", title="DBMS 2024 paper", topic="Joins",
        semester="5", academic_year="2024-25", doc_type="past_paper",
    ).json()

    def found(**params):  # type: ignore[no-untyped-def]
        return {i["id"] for i in bob.get("/library", params={"scope": "college", **params}).json()["items"]}

    assert found() == {a["id"], b["id"]}
    assert found(q="schedul") == {a["id"]}
    assert found(doc_type="past_paper") == {b["id"]}
    assert found(semester="4") == {a["id"]}
    assert found(year="2024-25") == {b["id"]}
    assert found(course="databases") == {b["id"]}
    assert found(topic="Joins", q="paper") == {b["id"]}
    assert found(q="100%") == set()
    assert found(institution=f"iit delhi {SUFFIX}") == {a["id"], b["id"]}
    assert found(institution=f"nit surat {SUFFIX}") == set()
    facets = bob.get("/library/facets", params={"scope": "college"}).json()
    assert facets["courses"] == ["Databases", "Operating Systems"]
    assert facets["semesters"] == ["4", "5"] and len(facets["institutions"]) == 1 and facets["institutions"][0].startswith("IIT Delhi ")
    titles = [i["title"] for i in bob.get("/library", params={"scope": "college", "sort": "title"}).json()["items"]]
    assert titles == ["DBMS 2024 paper", "Scheduling notes"]


def test_preview_is_inline_for_pdfs_and_text_and_a_download_for_other_types(make_user):  # type: ignore[no-untyped-def]
    alice = student(make_user, "Alice", "IIT Delhi")
    material_id, _ = material(alice, "plain.txt", data=b"Just text.\n")
    item = publish(alice, material_id, visibility="private").json()
    assert item["previewable"] is True
    inline = alice.get(f"/library/{item['id']}/file", params={"inline": "true"})
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.headers["x-frame-options"] == "SAMEORIGIN"
    download = alice.get(f"/library/{item['id']}/file")
    assert download.headers["content-disposition"].startswith("attachment")
    md, _ = material(alice, "notes.md", subject_name="Other")
    markdown = publish(alice, md, visibility="private").json()
    assert markdown["previewable"] is False
    forced = alice.get(f"/library/{markdown['id']}/file", params={"inline": "true"})
    assert forced.headers["content-disposition"].startswith("attachment")
