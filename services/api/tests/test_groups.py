"""Study groups and the shared library, against a real database."""

import asyncio
import uuid
from typing import Any

import pytest
from mindnest_api.routes import groups as groups_module
from mindnest_core.db import make_engine
from mindnest_core.grouplogic import HIDE_AT_REPORTS, MAX_GROUPS_PER_USER
from mindnest_core.settings import get_settings
from sqlalchemy import text

NOTES = b"# Processes\n\nA process is a program in execution.\n"
OTHER = b"# Threads\n\nThreads share memory inside a process.\n"


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


def subject(user, name="Operating Systems"):  # type: ignore[no-untyped-def]
    response = user.post("/subjects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(user, subject_id=None, name="notes.md", data=NOTES, kind="note"):  # type: ignore[no-untyped-def]
    subject_id = subject_id or subject(user)
    response = user.post(f"/subjects/{subject_id}/materials", files={"file": (name, data)}, data={"kind": kind})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def make_group(owner, name="Sem 3 CSE"):  # type: ignore[no-untyped-def]
    response = owner.post("/groups", json={"name": name, "description": "Class notes"})
    assert response.status_code == 201, response.text
    return response.json()


def join(user, group, code=None):  # type: ignore[no-untyped-def]
    return user.post("/groups/join", json={"code": code or group["join_code"]})


def share(user, group_id, material_id, **extra):  # type: ignore[no-untyped-def]
    body = {"material_id": material_id, "confirm_rights": True, **extra}
    return user.post(f"/groups/{group_id}/items", json=body)


def members(*users, group, owner):  # type: ignore[no-untyped-def]
    for user in users:
        assert join(user, group).status_code == 200


# ------------------------------------------------------------------ making and joining


def test_a_new_group_has_an_owner_and_a_code_only_the_owner_sees(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user("Owner"), make_user("Other")
    group = make_group(owner)
    assert group["role"] == "owner" and group["member_count"] == 1 and group["item_count"] == 0
    code = group["join_code"]
    assert len(code) == 11 and code[5] == "-"
    assert [g["id"] for g in owner.get("/groups").json()] == [group["id"]]
    assert other.get("/groups").json() == []
    joined = join(other, group).json()
    assert joined["role"] == "member" and joined["join_code"] is None and joined["member_count"] == 2
    assert other.get(f"/groups/{group['id']}").json()["join_code"] is None


def test_names_and_descriptions_are_checked(make_user):  # type: ignore[no-untyped-def]
    owner = make_user()
    assert owner.post("/groups", json={"name": "x"}).status_code == 422
    assert owner.post("/groups", json={"name": "ok name", "description": "d" * 301}).status_code == 422
    assert owner.post("/groups", json={"name": "  Physics club  "}).json()["name"] == "Physics club"


def test_a_code_works_however_it_is_typed(make_user):  # type: ignore[no-untyped-def]
    owner = make_user()
    group = make_group(owner)
    code = group["join_code"]
    for typed in (code.lower(), code.replace("-", " "), f"  {code}  "):
        assert join(make_user(), group, typed).status_code == 200


def test_a_wrong_or_malformed_code_gives_one_answer(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    for code in ("ABCDE-FGH23", "nonsense", "A" * 40, "0000000000"):
        response = join(user, {"join_code": code})
        assert response.status_code == 404 and response.json()["code"] == "group_not_found"


def test_joining_twice_is_harmless(make_user):  # type: ignore[no-untyped-def]
    owner, student = make_user(), make_user()
    group = make_group(owner)
    join(student, group)
    again = join(student, group)
    assert again.status_code == 200 and again.json()["member_count"] == 2
    assert join(owner, group).json()["role"] == "owner"


def test_a_group_has_a_member_limit_but_members_can_still_come_back(make_user, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(groups_module, "MAX_MEMBERS", 2)
    owner, a, b = make_user(), make_user(), make_user()
    group = make_group(owner)
    assert join(a, group).status_code == 200
    full = join(b, group)
    assert full.status_code == 409 and full.json()["code"] == "group_full"
    assert b.get("/groups").json() == []
    assert join(a, group).status_code == 200  # an existing member is not thrown out


def test_a_student_can_be_in_only_so_many_groups(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    for index in range(MAX_GROUPS_PER_USER):
        make_group(user, f"Group {index}")
    refused = user.post("/groups", json={"name": "One too many"})
    assert refused.status_code == 409 and refused.json()["code"] == "too_many_groups"
    other_group = make_group(make_user())
    assert join(user, other_group).json()["code"] == "too_many_groups"


def test_outsiders_cannot_see_anything_about_a_group(make_user):  # type: ignore[no-untyped-def]
    owner, outsider = make_user(), make_user()
    group = make_group(owner)
    item = share(owner, group["id"], upload(owner)).json()
    gid, iid = group["id"], item["id"]
    for response in (
        outsider.get(f"/groups/{gid}"),
        outsider.get(f"/groups/{gid}/items"),
        outsider.get(f"/groups/{gid}/items/{iid}/download"),
        outsider.patch(f"/groups/{gid}", json={"name": "Mine now"}),
        outsider.post(f"/groups/{gid}/code"),
        outsider.delete(f"/groups/{gid}"),
        outsider.delete(f"/groups/{gid}/items/{iid}"),
        outsider.post(f"/groups/{gid}/leave"),
        share(outsider, gid, upload(outsider)),
        outsider.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other"}),
    ):
        assert response.status_code == 404, response.text
    assert owner.get(f"/groups/{gid}").json()["name"] == "Sem 3 CSE"


def test_members_are_listed_by_name_without_email(make_user):  # type: ignore[no-untyped-def]
    owner, student = make_user("Asha Patel"), make_user("Ravi Shah")
    group = make_group(owner)
    join(student, group)
    detail = student.get(f"/groups/{group['id']}").json()
    assert [(m["display_name"], m["role"], m["is_me"]) for m in detail["members"]] == [
        ("Asha Patel", "owner", False), ("Ravi Shah", "member", True),
    ]
    assert owner.email not in str(detail) and student.email not in str(detail)


# ------------------------------------------------------------------ owner tools


def test_only_the_owner_can_rename_and_change_the_code(make_user):  # type: ignore[no-untyped-def]
    owner, student = make_user(), make_user()
    group = make_group(owner)
    join(student, group)
    gid = group["id"]
    assert student.patch(f"/groups/{gid}", json={"name": "Hijacked"}).status_code == 403
    assert student.post(f"/groups/{gid}/code").status_code == 403
    assert owner.patch(f"/groups/{gid}", json={"name": "Renamed", "description": ""}).json()["name"] == "Renamed"
    assert owner.patch(f"/groups/{gid}", json={"name": None}).status_code == 422
    fresh = owner.post(f"/groups/{gid}/code").json()["join_code"]
    assert fresh != group["join_code"]
    late = make_user()
    assert join(late, {"join_code": group["join_code"]}).status_code == 404
    assert join(late, {"join_code": fresh}).status_code == 200
    assert student.get("/groups").json()[0]["id"] == gid  # existing members stay


def test_the_owner_can_remove_a_member_and_their_files(make_user, storage):  # type: ignore[no-untyped-def]
    owner, student, other = make_user(), make_user(), make_user()
    group = make_group(owner)
    members(student, other, group=group, owner=owner)
    gid = group["id"]
    item = share(student, gid, upload(student)).json()
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert key in storage.objects
    sid = student.id
    assert other.delete(f"/groups/{gid}/members/{sid}").status_code == 403
    assert owner.delete(f"/groups/{gid}/members/{owner.id}").json()["code"] == "owner_cannot_leave"
    assert owner.delete(f"/groups/{gid}/members/{uuid.uuid4()}").status_code == 404
    assert owner.delete(f"/groups/{gid}/members/{sid}").status_code == 204
    assert key not in storage.objects
    assert student.get(f"/groups/{gid}").status_code == 404
    assert owner.get(f"/groups/{gid}/items").json() == []


def test_a_member_can_leave_and_takes_their_files_with_them(make_user, storage):  # type: ignore[no-untyped-def]
    owner, student = make_user(), make_user()
    group = make_group(owner)
    join(student, group)
    gid = group["id"]
    item = share(student, gid, upload(student)).json()
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert student.post(f"/groups/{gid}/leave").status_code == 204
    assert key not in storage.objects
    assert student.get("/groups").json() == []
    assert owner.get(f"/groups/{gid}").json()["member_count"] == 1
    assert owner.post(f"/groups/{gid}/leave").json()["code"] == "owner_cannot_leave"


def test_deleting_a_group_removes_its_files(make_user, storage):  # type: ignore[no-untyped-def]
    owner, student = make_user(), make_user()
    group = make_group(owner)
    join(student, group)
    gid = group["id"]
    item = share(student, gid, upload(student)).json()
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert student.delete(f"/groups/{gid}").status_code == 403
    assert owner.delete(f"/groups/{gid}").status_code == 204
    assert key not in storage.objects
    assert student.get("/groups").json() == [] and owner.get(f"/groups/{gid}").status_code == 404
    assert sql("SELECT count(*) FROM shared_items WHERE group_id = :g", g=gid)[0][0] == 0


# ------------------------------------------------------------------ sharing files


def test_a_shared_file_is_a_copy_that_every_member_can_download(make_user, storage):  # type: ignore[no-untyped-def]
    owner, student = make_user("Asha"), make_user("Ravi")
    group = make_group(owner)
    join(student, group)
    gid = group["id"]
    material = upload(student, name="processes.md", kind="past_paper")
    response = share(student, gid, material, note="Chapter 1 summary")
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["filename"] == "processes.md" and item["kind"] == "past_paper" and item["note"] == "Chapter 1 summary"
    assert item["shared_by_name"] == "Ravi" and item["mine"] is True and item["status"] == "active"
    assert item["size_bytes"] == len(NOTES) and item["reports"] is None
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert key.startswith(f"shared/{gid}/") and key != sql("SELECT storage_key FROM materials WHERE id = :m", m=material)[0][0]
    listed = owner.get(f"/groups/{gid}/items").json()
    assert [(i["filename"], i["mine"], i["shared_by_name"]) for i in listed] == [("processes.md", False, "Ravi")]
    assert owner.get("/groups").json()[0]["item_count"] == 1
    downloaded = owner.get(f"/groups/{gid}/items/{item['id']}/download")
    assert downloaded.status_code == 200 and downloaded.content == NOTES
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in downloaded.headers["content-disposition"]
    # The student deletes the original: the group's copy stays.
    assert student.delete(f"/materials/{material}").status_code == 204
    assert owner.get(f"/groups/{gid}/items/{item['id']}/download").content == NOTES


def test_a_shared_file_records_where_it_came_from_and_what_each_member_may_do(make_user, storage):  # type: ignore[no-untyped-def]
    owner, student, other = make_user("Asha"), make_user("Ravi"), make_user("Meera")
    group = make_group(owner)
    members(student, other, group=group, owner=owner)
    gid = group["id"]
    material = upload(student, name="scheduling.md")
    response = share(
        student, gid, material, author="Prof. Rao", institution="GEC Bhuj", rights="permitted"
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["course_name"] == "Operating Systems"
    assert (item["author"], item["institution"], item["rights"]) == ("Prof. Rao", "GEC Bhuj", "permitted")
    assert item["can_remove"] is True and item["can_report"] is False  # my own file
    seen = other.get(f"/groups/{gid}/items").json()[0]
    assert seen["course_name"] == "Operating Systems" and seen["author"] == "Prof. Rao"
    assert seen["can_remove"] is False and seen["can_report"] is True
    assert owner.get(f"/groups/{gid}/items").json()[0]["can_remove"] is True  # the owner moderates
    # Without the extra fields a file is the sharer's own work.
    plain = share(student, gid, upload(student, name="plain.md", data=b"# other\n")).json()
    assert (plain["author"], plain["institution"], plain["rights"]) == ("", "", "own_work")
    assert share(student, gid, upload(student, name="x.md", data=b"# x\n"), rights="stolen").status_code == 422


def test_sharing_needs_confirmation_a_real_file_and_no_duplicates(make_user):  # type: ignore[no-untyped-def]
    owner, other = make_user(), make_user()
    group = make_group(owner)
    gid = group["id"]
    material = upload(owner)
    unconfirmed = owner.post(f"/groups/{gid}/items", json={"material_id": material, "confirm_rights": False})
    assert unconfirmed.status_code == 422 and unconfirmed.json()["code"] == "rights_required"
    assert share(owner, gid, str(uuid.uuid4())).status_code == 404
    assert share(owner, gid, upload(other)).status_code == 404  # someone else's file
    assert share(owner, gid, material, note="n" * 301).status_code == 422
    assert share(owner, gid, material).status_code == 201
    again = share(owner, gid, material)
    assert again.status_code == 409 and again.json()["code"] == "already_shared"


def test_a_file_whose_contents_do_not_match_its_type_is_refused(make_user, storage):  # type: ignore[no-untyped-def]
    owner = make_user()
    group = make_group(owner)
    material = upload(owner, name="slides.pdf", data=b"%PDF-1.4 fake")
    key = sql("SELECT storage_key FROM materials WHERE id = :m", m=material)[0][0]
    storage.objects[key] = b"MZ\x90\x00 not a pdf"
    response = share(owner, group["id"], material)
    assert response.status_code == 415
    assert sql("SELECT count(*) FROM shared_items WHERE group_id = :g", g=group["id"])[0][0] == 0


def test_the_library_has_a_size_limit(make_user, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(groups_module, "MAX_ITEMS", 1)
    owner = make_user()
    group = make_group(owner)
    first, second = upload(owner), upload(owner, name="second.md", data=OTHER)
    assert share(owner, group["id"], first).status_code == 201
    full = share(owner, group["id"], second)
    assert full.status_code == 409 and full.json()["code"] == "group_library_full"


def test_the_picker_lists_only_my_own_files(make_user):  # type: ignore[no-untyped-def]
    mine, theirs = make_user(), make_user()
    upload(mine, name="mine.md")
    upload(theirs, name="theirs.md")
    listed = mine.get("/shareable-materials").json()
    assert [(m["filename"], m["subject_name"]) for m in listed] == [("mine.md", "Operating Systems")]


def test_a_member_can_copy_a_shared_file_into_their_own_subject(make_user, storage, queue):  # type: ignore[no-untyped-def]
    owner, student = make_user(), make_user()
    group = make_group(owner)
    join(student, group)
    gid = group["id"]
    item = share(owner, gid, upload(owner, kind="past_paper")).json()
    mine = subject(student, "My OS")
    response = student.post(f"/groups/{gid}/items/{item['id']}/add", json={"subject_id": mine})
    assert response.status_code == 201, response.text
    material_id = response.json()["material_id"]
    copied = student.get(f"/materials/{material_id}").json()
    assert copied["filename"] == "notes.md" and copied["kind"] == "past_paper" and copied["subject_id"] == mine
    assert copied["status"] == "uploaded"
    assert storage.objects[f"materials/{student.id}/{material_id}.md"] == NOTES
    assert (material_id, student.id) in queue.jobs
    # It belongs to the student alone: the owner cannot see it.
    assert owner.get(f"/materials/{material_id}").status_code == 404
    # Another student's subject is not an option.
    assert student.post(f"/groups/{gid}/items/{item['id']}/add", json={"subject_id": subject(owner)}).status_code == 404


def test_removing_a_shared_file(make_user, storage):  # type: ignore[no-untyped-def]
    owner, sharer, bystander = make_user(), make_user(), make_user()
    group = make_group(owner)
    members(sharer, bystander, group=group, owner=owner)
    gid = group["id"]
    first = share(sharer, gid, upload(sharer)).json()
    second = share(sharer, gid, upload(sharer, name="second.md", data=OTHER)).json()
    keys = {i: sql("SELECT storage_key FROM shared_items WHERE id = :i", i=i)[0][0] for i in (first["id"], second["id"])}
    assert bystander.delete(f"/groups/{gid}/items/{first['id']}").status_code == 404
    assert keys[first["id"]] in storage.objects
    assert sharer.delete(f"/groups/{gid}/items/{first['id']}").status_code == 204
    assert owner.delete(f"/groups/{gid}/items/{second['id']}").status_code == 204
    assert not any(key in storage.objects for key in keys.values())
    assert owner.delete(f"/groups/{gid}/items/{second['id']}").status_code == 404


# ------------------------------------------------------------------ reports


def reporters(count, group, make_user):  # type: ignore[no-untyped-def]
    people = [make_user(f"Reporter {i}") for i in range(count)]
    for person in people:
        join(person, group)
    return people


def test_enough_different_reports_hide_a_file_until_the_owner_decides(make_user):  # type: ignore[no-untyped-def]
    owner, sharer = make_user("Owner"), make_user("Sharer")
    group = make_group(owner)
    join(sharer, group)
    gid = group["id"]
    item = share(sharer, gid, upload(sharer)).json()
    iid = item["id"]
    people = reporters(HIDE_AT_REPORTS, group, make_user)

    for index, person in enumerate(people):
        response = person.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "copyright", "note": "from a book"})
        assert response.status_code == 200, response.text
        assert response.json()["hidden"] is (index == len(people) - 1)
    # The same student reporting again does not add up.
    assert people[0].post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other"}).status_code == 404

    # Hidden from ordinary members, still visible to the sharer and the owner.
    assert people[0].get(f"/groups/{gid}/items").json() == []
    assert people[0].get(f"/groups/{gid}/items/{iid}/download").status_code == 404
    assert owner.get("/groups").json()[0]["item_count"] == 0
    seen_by_owner = owner.get(f"/groups/{gid}/items").json()[0]
    assert seen_by_owner["status"] == "hidden" and seen_by_owner["reports"] == HIDE_AT_REPORTS
    assert sharer.get(f"/groups/{gid}/items").json()[0]["status"] == "hidden"
    assert sharer.get(f"/groups/{gid}/items").json()[0]["reports"] is None

    # The sharer cannot bring it back; the owner can, which clears the reports.
    assert sharer.post(f"/groups/{gid}/items/{iid}/restore").status_code == 403
    assert owner.post(f"/groups/{gid}/items/{iid}/restore").json() == {"hidden": False}
    restored = people[0].get(f"/groups/{gid}/items").json()[0]
    assert restored["status"] == "active" and restored["reported_by_me"] is False
    assert owner.get(f"/groups/{gid}/items").json()[0]["reports"] == 0


def test_one_report_does_not_hide_a_file_and_is_counted_once(make_user):  # type: ignore[no-untyped-def]
    owner, sharer = make_user(), make_user()
    group = make_group(owner)
    join(sharer, group)
    gid = group["id"]
    iid = share(sharer, gid, upload(sharer)).json()["id"]
    (reporter,) = reporters(1, group, make_user)
    first = reporter.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "wrong_content"})
    again = reporter.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other", "note": "changed my mind"})
    assert first.json() == again.json() == {"hidden": False}
    assert owner.get(f"/groups/{gid}/items").json()[0]["reports"] == 1
    assert reporter.get(f"/groups/{gid}/items").json()[0]["reported_by_me"] is True


def test_reports_are_validated_and_a_sharer_cannot_report_their_own_file(make_user):  # type: ignore[no-untyped-def]
    owner = make_user()
    group = make_group(owner)
    gid = group["id"]
    iid = share(owner, gid, upload(owner)).json()["id"]
    assert owner.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other"}).json()["code"] == "own_item"
    (member,) = reporters(1, group, make_user)
    assert member.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "spam"}).status_code == 422
    assert member.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other", "note": "x" * 301}).status_code == 422


def test_report_notes_are_only_visible_to_the_owner_and_the_reporter(make_user):  # type: ignore[no-untyped-def]
    owner, sharer = make_user(), make_user()
    group = make_group(owner)
    join(sharer, group)
    gid = group["id"]
    iid = share(sharer, gid, upload(sharer)).json()["id"]
    (reporter,) = reporters(1, group, make_user)
    reporter.post(f"/groups/{gid}/items/{iid}/report", json={"reason": "other", "note": "private worry"})
    assert "private worry" not in str(sharer.get(f"/groups/{gid}/items").json())
    assert "private worry" not in str(sharer.get(f"/groups/{gid}").json())
    assert sql("SELECT count(*) FROM shared_item_reports WHERE item_id = :i", i=iid)[0][0] == 1


# ------------------------------------------------------------------ safety of what is copied


@pytest.mark.parametrize("name", ["../../evil.md", "a‮txt.md"])
def test_odd_filenames_never_reach_storage_keys(make_user, storage, name):  # type: ignore[no-untyped-def]
    owner = make_user()
    group = make_group(owner)
    item = share(owner, group["id"], upload(owner, name=name)).json()
    key = sql("SELECT storage_key FROM shared_items WHERE id = :i", i=item["id"])[0][0]
    assert ".." not in key and "evil" not in key and key.startswith("shared/")
