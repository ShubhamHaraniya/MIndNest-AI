"""Sign in with Google, with Google's token endpoint replaced by a fake."""

import asyncio
import base64
import hashlib
import json
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from mindnest_api.routes.google_auth import FLOW_COOKIE, safe_next
from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text

DOMAIN = "mindnest-tests.dev"
CLIENT_ID = "test-client-id.apps.googleusercontent.com"
SESSION = get_settings().session_cookie_name


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


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def id_token(nonce: str, **claims: Any) -> str:
    body = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": uuid.uuid4().hex,
        "email": f"{uuid.uuid4().hex[:10]}@{DOMAIN}",
        "email_verified": True,
        "name": "Asha Patel",
        "nonce": nonce,
        "exp": int(time.time()) + 3600,
        **claims,
    }
    return ".".join([b64(b'{"alg":"RS256"}'), b64(json.dumps(body).encode()), "sig"])


class Visit:
    """One browser going to Google and coming back."""

    def __init__(self, client: TestClient, google: Any) -> None:
        self.client, self.google = client, google
        self.state = self.nonce = self.challenge = ""
        self.cookie = ""

    def start(self, **params: str) -> Any:
        self.client.cookies.clear()
        response = self.client.get(
            "/api/v1/auth/google/start", params=params, follow_redirects=False
        )
        if response.status_code == 303:
            query = parse_qs(urlparse(response.headers["location"]).query)
            self.state = query["state"][0]
            self.nonce = query["nonce"][0]
            self.challenge = query["code_challenge"][0]
            self.cookie = response.cookies.get(FLOW_COOKIE) or ""
        self.client.cookies.clear()
        return response

    def back(self, token: str | None = None, *, state: str | None = None, cookie: str | None = None,
             **query: str) -> Any:
        """Google redirects the browser to the callback."""
        if token is not None:
            self.google.token = token
        params = {"code": "one-time-code", "state": self.state if state is None else state, **query}
        params = {key: value for key, value in params.items() if value != ""}
        cookie_value = self.cookie if cookie is None else cookie
        headers = {"cookie": f"{FLOW_COOKIE}={cookie_value}"} if cookie_value else {}
        self.client.cookies.clear()
        response = self.client.get(
            "/api/v1/auth/google/callback", params=params, headers=headers, follow_redirects=False
        )
        self.client.cookies.clear()
        return response


def signed_in(response: Any) -> str | None:
    return response.cookies.get(SESSION)


def where(response: Any) -> str:
    return str(response.headers["location"])


def test_the_sign_in_page_learns_whether_google_is_set_up(anon, google):
    assert anon.get("/auth/providers").json() == {"google": True}


def test_the_button_is_off_until_google_is_configured(anon, client):
    assert anon.get("/auth/providers").json() == {"google": False}
    response = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert response.status_code == 503 and response.json()["code"] == "google_not_configured"


def test_start_sends_the_browser_to_google_with_pkce_state_and_nonce(client, google):
    visit = Visit(client, google)
    response = visit.start(lang="hi")
    assert response.status_code == 303
    url = urlparse(where(response))
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"][0].endswith("/api/v1/auth/google/callback")
    assert "openid" in query["scope"][0] and "email" in query["scope"][0]
    assert len(visit.state) >= 20 and len(visit.nonce) >= 20 and visit.state != visit.nonce
    header = response.headers["set-cookie"].lower()
    assert FLOW_COOKIE in header and "httponly" in header and "samesite=lax" in header


def test_a_new_student_is_created_and_signed_in(client, google):
    visit = Visit(client, google)
    visit.start(lang="gu")
    email = f"{uuid.uuid4().hex[:10]}@{DOMAIN}"
    response = visit.back(id_token(visit.nonce, email=email, name="Asha Patel"))
    assert response.status_code == 303 and where(response).endswith("/onboarding")
    token = signed_in(response)
    assert token
    # PKCE: the verifier sent to Google matches the challenge sent in the first redirect.
    verifier = google.calls[-1]["verifier"]
    assert b64(hashlib.sha256(verifier.encode()).digest()) == visit.challenge

    me = client.get("/api/v1/auth/me", headers={"cookie": f"{SESSION}={token}"}).json()
    assert me["email"] == email and me["display_name"] == "Asha Patel"
    assert me["email_verified"] is True and me["ui_language"] == "gu"
    row = sql("SELECT password_hash FROM users WHERE lower(email) = :e", e=email)[0]
    assert row[0] is None
    client.cookies.clear()
    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "anything at all"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_credentials"
    client.cookies.clear()


def test_signing_in_again_reuses_the_same_account(client, google):
    first = Visit(client, google)
    first.start()
    sub, email = uuid.uuid4().hex, f"{uuid.uuid4().hex[:10]}@{DOMAIN}"
    a = first.back(id_token(first.nonce, sub=sub, email=email))
    second = Visit(client, google)
    second.start()
    b = second.back(id_token(second.nonce, sub=sub, email=email))
    assert signed_in(a) and signed_in(b) and signed_in(a) != signed_in(b)
    assert sql("SELECT count(*) FROM users WHERE lower(email) = :e", e=email)[0][0] == 1
    assert sql("SELECT count(*) FROM user_identities WHERE subject = :s", s=sub)[0][0] == 1


def test_an_existing_account_is_linked_not_duplicated(client, google, make_user):
    student = make_user()
    sql("UPDATE users SET email_verified_at = now() WHERE id = :i", i=student.id)
    visit = Visit(client, google)
    visit.start()
    response = visit.back(id_token(visit.nonce, email=student.email))
    token = signed_in(response)
    assert token
    me = client.get("/api/v1/auth/me", headers={"cookie": f"{SESSION}={token}"}).json()
    client.cookies.clear()
    assert me["id"] == student.id
    # A confirmed account keeps its password after linking.
    login = client.post(
        "/api/v1/auth/login", json={"email": student.email, "password": student.password}
    )
    client.cookies.clear()
    assert login.status_code == 200
    assert sql("SELECT count(*) FROM user_identities WHERE user_id = :i", i=student.id)[0][0] == 1


def test_linking_an_unconfirmed_account_removes_the_password_and_old_sessions(
    client, google, make_user
):
    squatter = make_user()  # registered with an address nobody has confirmed
    assert sql("SELECT email_verified_at FROM users WHERE id = :i", i=squatter.id)[0][0] is None
    visit = Visit(client, google)
    visit.start()
    response = visit.back(id_token(visit.nonce, email=squatter.email))
    assert signed_in(response)
    assert sql("SELECT password_hash FROM users WHERE id = :i", i=squatter.id)[0][0] is None
    assert sql("SELECT email_verified_at FROM users WHERE id = :i", i=squatter.id)[0][0] is not None
    # The password the squatter chose no longer works, and the session they held is gone.
    assert squatter.get("/auth/me").status_code == 401
    client.cookies.clear()
    login = client.post(
        "/api/v1/auth/login", json={"email": squatter.email, "password": squatter.password}
    )
    client.cookies.clear()
    assert login.status_code == 401


def test_an_email_google_has_not_verified_is_refused(client, google):
    visit = Visit(client, google)
    visit.start()
    email = f"{uuid.uuid4().hex[:10]}@{DOMAIN}"
    response = visit.back(id_token(visit.nonce, email=email, email_verified=False))
    assert response.status_code == 303 and "error=google_unverified" in where(response)
    assert not signed_in(response)
    assert sql("SELECT count(*) FROM users WHERE lower(email) = :e", e=email)[0][0] == 0


def test_a_callback_without_the_matching_state_is_refused(client, google):
    visit = Visit(client, google)
    visit.start()
    token = id_token(visit.nonce)
    for response in (
        visit.back(token, state="not-the-state"),
        visit.back(token, state=""),
        visit.back(token, cookie=""),  # a different browser, or an expired attempt
        visit.back(token, cookie=visit.cookie[:-4] + "AAAA"),  # tampered cookie
    ):
        assert "error=google_failed" in where(response) and not signed_in(response)
    assert google.calls == []  # nothing was even sent to Google


def test_an_expired_attempt_is_refused(client, google, monkeypatch):
    visit = Visit(client, google)
    visit.start()
    real = time.time
    monkeypatch.setattr("mindnest_core.googleoauth.time.time", lambda: real() + 3600)
    response = visit.back(id_token(visit.nonce))
    assert "error=google_failed" in where(response)


def test_a_token_for_another_app_or_another_attempt_is_refused(client, google):
    visit = Visit(client, google)
    visit.start()
    for token in (
        id_token(visit.nonce, aud="someone-elses-app"),
        id_token("a-different-nonce"),
        id_token(visit.nonce, iss="https://evil.example"),
        id_token(visit.nonce, exp=int(time.time()) - 10),
        "not.a.token",
    ):
        response = visit.back(token)
        assert "error=google_failed" in where(response) and not signed_in(response)


def test_google_being_down_is_a_clean_failure(client, google):
    visit = Visit(client, google)
    visit.start()
    google.fail = True
    response = visit.back(id_token(visit.nonce))
    assert "error=google_failed" in where(response) and not signed_in(response)


def test_cancelling_on_googles_page_returns_to_sign_in(client, google):
    visit = Visit(client, google)
    visit.start()
    response = visit.back(code="", error="access_denied")
    assert "error=google_cancelled" in where(response) and not signed_in(response)


def test_a_suspended_account_cannot_sign_in_with_google(client, google, make_user):
    student = make_user()
    sql("UPDATE users SET status = 'suspended' WHERE id = :i", i=student.id)
    visit = Visit(client, google)
    visit.start()
    response = visit.back(id_token(visit.nonce, email=student.email))
    assert "error=google_disabled" in where(response) and not signed_in(response)
    sql("UPDATE users SET status = 'active' WHERE id = :i", i=student.id)


def test_a_finished_student_goes_where_they_were_headed_and_nowhere_else(client, google):
    visit = Visit(client, google)
    visit.start(next="/quizzes")
    sub, email = uuid.uuid4().hex, f"{uuid.uuid4().hex[:10]}@{DOMAIN}"
    visit.back(id_token(visit.nonce, sub=sub, email=email))
    sql("UPDATE users SET onboarding_completed_at = now() WHERE lower(email) = :e", e=email)

    for wanted, expected in (("/quizzes", "/quizzes"), ("//evil.example", "/dashboard"),
                             ("https://evil.example", "/dashboard"), ("/a\\b", "/dashboard")):
        again = Visit(client, google)
        again.start(next=wanted)
        response = again.back(id_token(again.nonce, sub=sub, email=email))
        assert urlparse(where(response)).path == expected


def test_next_paths_are_checked():
    assert safe_next("/planner") == "/planner"
    assert safe_next("/quizzes?x=1") == "/quizzes?x=1"
    for bad in (None, "", "evil.com", "//evil.com", "https://evil.com", "/a\\b", "/a\nb", "/" + "x" * 400):
        assert safe_next(bad) == "/dashboard"
