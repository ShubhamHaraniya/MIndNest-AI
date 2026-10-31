"""Sign in with Google.

The browser is sent to Google, signs in there, and comes back to /auth/google/callback with a
one-time code. Three things protect the round trip: a random `state` (so the callback can only
complete a sign-in this browser started), PKCE (so a stolen code is useless) and a `nonce` inside
Google's identity token (so an old token cannot be replayed). All three live in one signed,
short-lived, HttpOnly cookie.

An existing account is linked only when Google says the email is verified. If the account's own
email was never confirmed, its password is removed on linking, so someone who registered an email
they do not own cannot keep a way in after the real owner signs in with Google.
"""

import logging
import secrets
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse, Response
from mindnest_core.googleoauth import (
    GoogleError,
    GoogleProfile,
    authorize_url,
    pkce_pair,
    profile_from_id_token,
    seal,
    unseal,
)
from mindnest_core.settings import get_settings, google_enabled, google_redirect
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import GoogleDep, LimiterDep, client_ip, set_session_cookie
from mindnest_api.errors import AppError
from mindnest_api.routes.auth import _create_session, _load_user

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("mindnest.google")

FLOW_COOKIE = "mindnest_oauth"
FLOW_PATH = "/api/v1/auth/google"
Lang = Literal["en", "hi", "gu"]


class ProvidersOut(BaseModel):
    google: bool


@router.get("/providers", response_model=ProvidersOut)
async def providers() -> ProvidersOut:
    """Tells the sign-in page whether to show the Google button."""
    return ProvidersOut(google=google_enabled(get_settings()))


def safe_next(value: str | None, fallback: str = "/dashboard") -> str:
    """Only same-site paths: a crafted link must not send a signed-in student elsewhere."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    if any(ord(char) < 32 for char in value) or len(value) > 300:
        return fallback
    return value


def _flow_cookie(response: Response, value: str, max_age: int) -> None:
    response.set_cookie(
        FLOW_COOKIE,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",  # sent on the top-level redirect back from Google
        secure=get_settings().environment != "development",
        path=FLOW_PATH,
    )


def _fail(code: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{get_settings().web_base_url.rstrip('/')}/login?error={quote(code)}", status_code=303
    )
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/google/start")
async def google_start(
    request: Request,
    limiter: LimiterDep,
    next: Annotated[str | None, Query(max_length=300)] = None,
    lang: Lang = "en",
) -> Response:
    settings = get_settings()
    if not google_enabled(settings):
        raise AppError(503, "google_not_configured", "Sign in with Google is not set up yet.")
    await limiter.check(f"google:start:{client_ip(request)}", 30, 900)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = authorize_url(
        client_id=settings.google_client_id,
        redirect_uri=google_redirect(settings),
        state=state,
        challenge=challenge,
        nonce=nonce,
    )
    response = RedirectResponse(url, status_code=303)
    blob = seal(
        settings.secret_key,
        {"s": state, "v": verifier, "n": nonce, "next": safe_next(next), "lang": lang},
    )
    _flow_cookie(response, blob, 600)
    return response


async def _sign_in_or_link(
    session: AsyncSession, profile: GoogleProfile, lang: str
) -> tuple[Any, str]:
    """Return (user id, how): 'existing', 'linked' or 'created'. Raises AppError to refuse."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT i.user_id, u.status FROM user_identities i "
                    "JOIN users u ON u.id = i.user_id "
                    "WHERE i.provider = 'google' AND i.subject = :sub"
                ),
                {"sub": profile.subject},
            )
        )
        .mappings()
        .first()
    )
    if row is not None:
        if row["status"] != "active":
            raise AppError(403, "google_disabled", "This account is not active.")
        await session.execute(
            text(
                "UPDATE user_identities SET last_login_at = now(), email = :email "
                "WHERE provider = 'google' AND subject = :sub"
            ),
            {"sub": profile.subject, "email": profile.email},
        )
        return row["user_id"], "existing"

    if not profile.email_verified:
        raise AppError(403, "google_unverified", "Google has not verified this email address.")

    owner = (
        (
            await session.execute(
                text(
                    "SELECT id, status, email_verified_at FROM users "
                    "WHERE lower(email) = :email FOR UPDATE"
                ),
                {"email": profile.email},
            )
        )
        .mappings()
        .first()
    )
    how = "linked"
    if owner is not None:
        if owner["status"] != "active":
            raise AppError(403, "google_disabled", "This account is not active.")
        user_id = owner["id"]
        if owner["email_verified_at"] is None:
            # Whoever registered this address never proved they own it. Google just proved the
            # real owner does, so remove the password and every open session.
            await session.execute(
                text(
                    "UPDATE users SET password_hash = NULL, email_verified_at = now(), "
                    "updated_at = now() WHERE id = :id"
                ),
                {"id": user_id},
            )
            await session.execute(text("DELETE FROM sessions WHERE user_id = :id"), {"id": user_id})
    else:
        name = profile.name or profile.email.split("@")[0]
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name, ui_language, "
                    "email_verified_at) VALUES (:email, NULL, :name, :lang, now()) RETURNING id"
                ),
                {"email": profile.email, "name": name[:80], "lang": lang},
            )
        ).scalar_one()
        how = "created"
    await session.execute(
        text(
            "INSERT INTO user_identities (user_id, provider, subject, email, last_login_at) "
            "VALUES (:uid, 'google', :sub, :email, now())"
        ),
        {"uid": user_id, "sub": profile.subject, "email": profile.email},
    )
    return user_id, how


@router.get("/google/callback")
async def google_callback(
    request: Request,
    google: GoogleDep,
    limiter: LimiterDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    settings = get_settings()
    if not google_enabled(settings):
        return _fail("google_not_configured")
    await limiter.check(f"google:callback:{client_ip(request)}", 30, 900)
    flow = unseal(settings.secret_key, request.cookies.get(FLOW_COOKIE))
    expected = flow.get("s") if flow else None
    # The state check comes first: without it this callback could be used to log a victim's
    # browser into the attacker's account.
    if (
        flow is None
        or not isinstance(expected, str)
        or not state
        or not secrets.compare_digest(state, expected)
    ):
        return _fail("google_failed")
    if error or not code:
        return _fail("google_cancelled")

    try:
        tokens = await google.exchange_code(code, str(flow["v"]), google_redirect(settings))
        profile = profile_from_id_token(
            str(tokens.get("id_token") or ""),
            client_id=settings.google_client_id,
            nonce=str(flow["n"]),
        )
    except GoogleError as exc:
        log.warning("google sign-in failed: %s", exc)
        return _fail("google_failed")

    lang = flow.get("lang") if flow.get("lang") in ("en", "hi", "gu") else "en"
    try:
        async with request.app.state.session_factory() as session, session.begin():
            user_id, how = await _sign_in_or_link(session, profile, str(lang))
            token = await _create_session(session, user_id, request)
            user = await _load_user(session, user_id)
    except AppError as exc:
        return _fail(exc.code)
    except IntegrityError:
        return _fail("google_failed")

    log.info("google sign-in: %s", how)
    base = settings.web_base_url.rstrip("/")
    target = safe_next(str(flow.get("next"))) if user.onboarding_completed else "/onboarding"
    response = RedirectResponse(f"{base}{target}", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    set_session_cookie(response, token)
    return response
