"""Account security: change password, other sign-ins, and the personal data export."""

import asyncio
from typing import Any

from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"


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


def sign_in(anon, user, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    """A second browser for the same account."""
    response = anon.post(
        "/auth/login",
        json={"email": user.email, "password": password},
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/130.0"},
    )
    assert response.status_code == 200, response.text
    return type(anon)(anon._client, response.cookies.get(get_settings().session_cookie_name))


def test_everything_here_needs_a_session(anon):  # type: ignore[no-untyped-def]
    assert anon.get("/me/security").status_code == 401
    assert anon.get("/me/sessions").status_code == 401
    assert anon.get("/me/export").status_code == 401
    assert (
        anon.post("/me/password", json={"current_password": "x", "new_password": "y" * 12}).status_code == 401
    )
    assert anon.post("/me/sessions/sign-out-others").status_code == 401


def test_change_password_signs_out_other_devices_but_not_this_one(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    laptop = sign_in(anon, user)

    changed = user.post("/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 204, changed.text

    assert user.get("/auth/me").status_code == 200  # this device stays signed in
    assert laptop.get("/auth/me").status_code == 401  # the other one does not
    assert (
        anon.post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 401
    )
    assert (
        anon.post("/auth/login", json={"email": user.email, "password": NEW_PASSWORD}).status_code == 200
    )


def test_change_password_checks_the_current_one(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    wrong = user.post("/me/password", json={"current_password": "not my password", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "wrong_password"
    # Nothing changed: the old password still signs in.
    assert anon.post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 200


def test_change_password_rejects_weak_or_unchanged_passwords(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    short = user.post("/me/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422
    same = user.post("/me/password", json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422
    assert same.json()["code"] == "password_unchanged"


def test_change_password_retires_unused_reset_links(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    anon.post("/auth/forgot-password", json={"email": user.email})
    token = mailer.last_token(user.email)
    assert user.post("/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 204
    used = anon.post("/auth/reset-password", json={"token": token, "new_password": "yet another passphrase"})
    assert used.status_code == 400
    assert used.json()["code"] == "invalid_token"


def test_google_only_account_has_no_password_to_change(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    sql("UPDATE users SET password_hash = NULL WHERE id = :i", i=user.id)
    assert user.get("/me/security").json() == {"has_password": False, "email_verified": False}
    response = user.post("/me/password", json={"current_password": "anything", "new_password": NEW_PASSWORD})
    assert response.status_code == 409
    assert response.json()["code"] == "no_password_set"


def test_sessions_list_names_devices_and_marks_this_one(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    sign_in(anon, user)
    items = user.get("/me/sessions").json()["items"]
    assert len(items) == 2
    assert sum(1 for item in items if item["current"]) == 1
    assert any(item["device"] == "Firefox · Windows" for item in items)
    # Only presentable fields are returned: no token, hash or raw user agent.
    for item in items:
        assert set(item) == {"id", "device", "created_at", "last_seen_at", "current"}


def test_sign_out_others_keeps_this_session(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    other = sign_in(anon, user)
    result = user.post("/me/sessions/sign-out-others")
    assert result.status_code == 200
    assert result.json() == {"signed_out": 1}
    assert user.get("/auth/me").status_code == 200
    assert other.get("/auth/me").status_code == 401
    assert user.post("/me/sessions/sign-out-others").json() == {"signed_out": 0}


def test_other_accounts_sessions_are_untouched(anon, make_user):  # type: ignore[no-untyped-def]
    mine, theirs = make_user(), make_user()
    theirs_second = sign_in(anon, theirs)
    mine.post("/me/sessions/sign-out-others")
    mine.post("/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert theirs.get("/auth/me").status_code == 200
    assert theirs_second.get("/auth/me").status_code == 200
    assert len(theirs.get("/me/sessions").json()["items"]) == 2


def test_export_is_your_own_data_and_holds_no_secrets(make_user):  # type: ignore[no-untyped-def]
    mine, theirs = make_user("Asha"), make_user("Other")
    assert mine.post("/subjects", json={"name": "Physics 101"}).status_code in (200, 201)
    assert theirs.post("/subjects", json={"name": "Secret Chemistry"}).status_code in (200, 201)

    response = mine.get("/me/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["profile"]["email"] == mine.email
    assert [s["name"] for s in body["subjects"]] == ["Physics 101"]
    raw = response.text.lower()
    assert "secret chemistry" not in raw
    for forbidden in ("password", "token", "api_key", "ciphertext", "storage_key", "$argon2"):
        assert forbidden not in raw, forbidden
