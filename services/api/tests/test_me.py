def test_patch_me_updates_only_the_fields_sent(make_user):  # type: ignore[no-untyped-def]
    user = make_user("Before")
    response = user.patch("/me", json={"display_name": "  After  ", "ui_language": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "After"
    assert body["ui_language"] == "hi"
    assert body["timezone"] == "UTC"
    assert user.get("/auth/me").json()["ui_language"] == "hi"


def test_timezone_must_exist(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.patch("/me", json={"timezone": "Asia/Kolkata"}).status_code == 200
    bad = user.patch("/me", json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "invalid_timezone"
    assert user.patch("/me", json={"timezone": "../etc/passwd"}).status_code == 422


def test_answer_language_can_be_set_and_cleared(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.patch("/me", json={"answer_language": "gu"}).json()["answer_language"] == "gu"
    assert user.patch("/me", json={"answer_language": None}).json()["answer_language"] is None


def test_other_fields_cannot_be_null_or_invalid(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.patch("/me", json={"display_name": None}).status_code == 422
    assert user.patch("/me", json={"display_name": "   "}).status_code == 422
    assert user.patch("/me", json={"ui_language": "fr"}).status_code == 422
    assert user.patch("/me", json={"onboarding_step": 9}).status_code == 422


def test_onboarding_progress_is_saved(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.patch("/me", json={"onboarding_step": 2}).json()["onboarding_step"] == 2
    done = user.patch("/me", json={"onboarding_completed": True}).json()
    assert done["onboarding_completed"] is True
    assert user.get("/auth/me").json()["onboarding_completed"] is True


def test_empty_patch_changes_nothing(make_user):  # type: ignore[no-untyped-def]
    user = make_user("Same")
    assert user.patch("/me", json={}).json()["display_name"] == "Same"


def test_users_cannot_change_someone_elses_profile(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user("Alice"), make_user("Bob")
    alice.patch("/me", json={"display_name": "Alice Changed"})
    assert bob.get("/auth/me").json()["display_name"] == "Bob"
