import uuid

PASSWORD = "correct horse battery"  # same value the make_user fixture signs up with


def _signup_body(**overrides):  # type: ignore[no-untyped-def]
    body = {
        "email": f"{uuid.uuid4().hex[:12]}@mindnest-tests.dev",
        "password": PASSWORD,
        "display_name": "  Asha Patel  ",
    }
    body.update(overrides)
    return body


def test_signup_signs_in_and_sends_verification_email(anon, mailer):  # type: ignore[no-untyped-def]
    body = _signup_body(email=f"Asha.{uuid.uuid4().hex[:8]}@MindNest-Tests.dev")
    response = anon.post("/auth/signup", json=body)
    assert response.status_code == 201
    user = response.json()
    assert user["display_name"] == "Asha Patel"
    assert user["email"] == body["email"].lower()
    assert user["email_verified"] is False
    assert user["onboarding_completed"] is False
    assert "password" not in response.text and "hash" not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert mailer.count(user["email"]) == 1


def test_signup_duplicate_email_is_rejected_case_insensitively(anon, make_user):  # type: ignore[no-untyped-def]
    existing = make_user()
    response = anon.post("/auth/signup", json=_signup_body(email=existing.email.upper()))
    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


def test_signup_validates_input(anon):  # type: ignore[no-untyped-def]
    assert anon.post("/auth/signup", json=_signup_body(password="short")).status_code == 422
    assert anon.post("/auth/signup", json=_signup_body(email="not-an-email")).status_code == 422
    assert anon.post("/auth/signup", json=_signup_body(display_name="   ")).status_code == 422
    assert anon.post("/auth/signup", json=_signup_body(ui_language="fr")).status_code == 422


def test_me_requires_a_session_and_returns_the_user(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user("Ravi")
    assert anon.get("/auth/me").status_code == 401
    response = user.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == user.email
    assert response.json()["display_name"] == "Ravi"


def test_login_success_and_failure_are_indistinguishable(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    ok = anon.post("/auth/login", json={"email": user.email.upper(), "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["id"] == user.id
    assert "mindnest_session=" in ok.headers["set-cookie"]

    wrong = anon.post("/auth/login", json={"email": user.email, "password": "wrong password!"})
    unknown = anon.post(
        "/auth/login", json={"email": "nobody@mindnest-tests.dev", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "invalid_credentials"
    assert wrong.json()["message"] == unknown.json()["message"]


def test_logout_invalidates_the_session_server_side(anon, make_user, client):  # type: ignore[no-untyped-def]
    user = make_user()
    stolen_token = user.token
    assert user.get("/auth/me").status_code == 200
    response = user.post("/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    # Replaying the old cookie value must fail: the session row is gone, not just the cookie.
    user.token = stolen_token
    assert user.get("/auth/me").status_code == 401


def test_logout_without_a_session_is_fine(anon):  # type: ignore[no-untyped-def]
    assert anon.post("/auth/logout").status_code == 204


def test_email_verification_is_single_use(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    token = mailer.last_token(user.email)
    assert anon.post("/auth/verify-email", json={"token": token}).status_code == 204
    assert user.get("/auth/me").json()["email_verified"] is True
    again = anon.post("/auth/verify-email", json={"token": token})
    assert again.status_code == 400
    assert again.json()["code"] == "invalid_token"
    bogus = anon.post("/auth/verify-email", json={"token": "x" * 40})
    assert bogus.status_code == 400


def test_resend_verification_replaces_the_old_link(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    first = mailer.last_token(user.email)
    assert anon.post("/auth/resend-verification").status_code == 401
    assert user.post("/auth/resend-verification").status_code == 204
    second = mailer.last_token(user.email)
    assert first != second
    assert anon.post("/auth/verify-email", json={"token": first}).status_code == 400
    assert anon.post("/auth/verify-email", json={"token": second}).status_code == 204
    # Already verified: nothing more is sent.
    sent = mailer.count(user.email)
    assert user.post("/auth/resend-verification").status_code == 204
    assert mailer.count(user.email) == sent


def test_forgot_password_never_reveals_whether_the_email_exists(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    known = anon.post("/auth/forgot-password", json={"email": user.email})
    unknown = anon.post("/auth/forgot-password", json={"email": "ghost@mindnest-tests.dev"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert mailer.count("ghost@mindnest-tests.dev") == 0
    assert mailer.count(user.email) == 2  # verification + reset


def test_password_reset_changes_password_and_signs_out_everywhere(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    anon.post("/auth/forgot-password", json={"email": user.email})
    token = mailer.last_token(user.email)

    weak = anon.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422

    new_password = "a brand new passphrase"
    done = anon.post("/auth/reset-password", json={"token": token, "new_password": new_password})
    assert done.status_code == 204

    assert user.get("/auth/me").status_code == 401  # old session revoked
    assert (
        anon.post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code
        == 401
    )
    assert (
        anon.post("/auth/login", json={"email": user.email, "password": new_password}).status_code
        == 200
    )
    reused = anon.post("/auth/reset-password", json={"token": token, "new_password": new_password})
    assert reused.status_code == 400


def test_a_verification_token_cannot_reset_a_password(anon, make_user, mailer):  # type: ignore[no-untyped-def]
    user = make_user()
    verify_token = mailer.last_token(user.email)
    response = anon.post(
        "/auth/reset-password", json={"token": verify_token, "new_password": "another good passphrase"}
    )
    assert response.status_code == 400
