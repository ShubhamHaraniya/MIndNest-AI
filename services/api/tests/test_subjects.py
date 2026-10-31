import uuid


def _create(user, name="Operating Systems", **extra):  # type: ignore[no-untyped-def]
    response = user.post("/subjects", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_subject(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    created = _create(
        user, "  Operating Systems  ", course_code="CS301", semester="5", description="   "
    )
    assert created["name"] == "Operating Systems"
    assert created["course_code"] == "CS301"
    assert created["description"] is None  # blank strings become null
    assert created["material_count"] == 0
    assert created["archived_at"] is None
    fetched = user.get(f"/subjects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_create_validation(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.post("/subjects", json={}).status_code == 422
    assert user.post("/subjects", json={"name": "   "}).status_code == 422
    assert user.post("/subjects", json={"name": "x" * 121}).status_code == 422


def test_update_changes_and_clears_fields(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject = _create(user, course_code="CS301", semester="5")
    updated = user.patch(
        f"/subjects/{subject['id']}", json={"name": "Systems", "course_code": None}
    ).json()
    assert updated["name"] == "Systems"
    assert updated["course_code"] is None
    assert updated["semester"] == "5"  # untouched
    assert user.patch(f"/subjects/{subject['id']}", json={"name": None}).status_code == 422
    assert user.patch(f"/subjects/{subject['id']}", json={"name": " "}).status_code == 422


def test_archive_and_unarchive_move_subjects_between_lists(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject = _create(user)
    archived = user.post(f"/subjects/{subject['id']}/archive").json()
    assert archived["archived_at"] is not None
    assert user.get("/subjects").json()["items"] == []
    assert user.get("/subjects?state=archived").json()["total"] == 1
    assert user.get("/subjects?state=all").json()["total"] == 1
    restored = user.post(f"/subjects/{subject['id']}/unarchive").json()
    assert restored["archived_at"] is None
    assert user.get("/subjects").json()["total"] == 1


def test_list_search_and_pagination(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    for index in range(5):
        _create(user, f"Course {index}", course_code=f"CODE{index}")
    _create(user, "100% Legit_Name")

    first = user.get("/subjects?limit=4").json()
    assert first["total"] == 6
    assert len(first["items"]) == 4
    assert first["next_cursor"]
    second = user.get(f"/subjects?limit=4&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 2
    assert second["next_cursor"] is None
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 6  # no repeats across pages

    assert user.get("/subjects?q=course 3").json()["total"] == 1
    assert user.get("/subjects?q=code2").json()["total"] == 1  # matches course code, case-insensitive
    # LIKE wildcards in the search box are literal characters, not patterns.
    assert user.get("/subjects?q=%25").json()["total"] == 1
    assert user.get("/subjects?q=_").json()["total"] == 1
    assert user.get("/subjects?cursor=not-a-cursor").status_code == 422
    assert user.get("/subjects?limit=0").status_code == 422
    assert user.get("/subjects?limit=101").status_code == 422


def test_delete_requires_confirmation_and_reports_impact(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    subject = _create(user)
    impact = user.get(f"/subjects/{subject['id']}/delete-impact")
    assert impact.status_code == 200
    assert impact.json() == {"materials": 0, "topics": 0, "conversations_kept": 0}

    refused = user.delete(f"/subjects/{subject['id']}")
    assert refused.status_code == 400
    assert refused.json()["code"] == "confirmation_required"
    assert refused.json()["details"]["materials"] == 0
    assert user.get(f"/subjects/{subject['id']}").status_code == 200

    assert user.delete(f"/subjects/{subject['id']}?confirm=true").status_code == 204
    assert user.get(f"/subjects/{subject['id']}").status_code == 404
    assert user.delete(f"/subjects/{subject['id']}?confirm=true").status_code == 404


def test_unknown_subject_is_404_and_bad_id_is_422(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get(f"/subjects/{uuid.uuid4()}").status_code == 404
    assert user.get("/subjects/not-a-uuid").status_code == 422


# --- cross-user isolation: every endpoint that touches a subject ---------------------------


def test_another_user_cannot_see_or_change_my_subject(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    secret = _create(alice, "Alice private course")
    sid = secret["id"]

    assert bob.get(f"/subjects/{sid}").status_code == 404
    assert bob.patch(f"/subjects/{sid}", json={"name": "Hacked"}).status_code == 404
    assert bob.post(f"/subjects/{sid}/archive").status_code == 404
    assert bob.post(f"/subjects/{sid}/unarchive").status_code == 404
    assert bob.get(f"/subjects/{sid}/delete-impact").status_code == 404
    assert bob.delete(f"/subjects/{sid}?confirm=true").status_code == 404
    assert bob.delete(f"/subjects/{sid}").status_code == 404  # 404, not "confirmation required"

    listing = bob.get("/subjects?state=all").json()
    assert listing["total"] == 0 and listing["items"] == []
    assert bob.get("/subjects?q=Alice").json()["total"] == 0

    intact = alice.get(f"/subjects/{sid}").json()
    assert intact["name"] == "Alice private course"
    assert intact["archived_at"] is None


def test_each_user_sees_only_their_own_subjects(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    _create(alice, "A1")
    _create(alice, "A2")
    _create(bob, "B1")
    assert {s["name"] for s in alice.get("/subjects").json()["items"]} == {"A1", "A2"}
    assert {s["name"] for s in bob.get("/subjects").json()["items"]} == {"B1"}
