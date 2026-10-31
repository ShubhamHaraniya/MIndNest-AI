"""Sign-up, sign-in, sign-out, email verification and password reset."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Request, Response
from mindnest_core.settings import get_settings
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_api.deps import (
    AuthUser,
    LimiterDep,
    MailerDep,
    clear_session_cookie,
    client_ip,
    set_session_cookie,
)
from mindnest_api.errors import AppError
from mindnest_api.mailer import reset_message, verification_message
from mindnest_api.schemas import USER_COLUMNS, Email, Language, UserOut
from mindnest_api.security import (
    burn_password_check,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Password = Annotated[str, Field(min_length=10, max_length=128)]


class SignupIn(BaseModel):
    email: Email
    password: Password
    display_name: DisplayName
    ui_language: Language = "en"


class LoginIn(BaseModel):
    email: Email
    password: Annotated[str, Field(min_length=1, max_length=128)]


class TokenIn(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=200)]


class ForgotIn(BaseModel):
    email: Email


class ResetIn(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=200)]
    new_password: Password


class StatusOut(BaseModel):
    status: str = "ok"


async def _load_user(session: AsyncSession, user_id) -> UserOut:  # type: ignore[no-untyped-def]
    row = (
        (
            await session.execute(
                text(f"SELECT {USER_COLUMNS} FROM users u WHERE u.id = :id"), {"id": user_id}
            )
        )
        .mappings()
        .one()
    )
    return UserOut(**row)


async def _create_session(session: AsyncSession, user_id, request: Request) -> str:  # type: ignore[no-untyped-def]
    token = new_token()
    await session.execute(
        text(
            "INSERT INTO sessions (user_id, token_hash, expires_at, user_agent) "
            "VALUES (:uid, :hash, now() + make_interval(days => :days), :ua)"
        ),
        {
            "uid": user_id,
            "hash": hash_token(token),
            "days": get_settings().session_ttl_days,
            "ua": (request.headers.get("user-agent") or "")[:255] or None,
        },
    )
    return token


async def _issue_email_token(session: AsyncSession, user_id, kind: str) -> str:  # type: ignore[no-untyped-def]
    """Create a fresh single-use token and retire any earlier unused ones of the same kind."""
    settings = get_settings()
    await session.execute(
        text(
            "UPDATE email_tokens SET used_at = now() "
            "WHERE user_id = :uid AND kind = :kind AND used_at IS NULL"
        ),
        {"uid": user_id, "kind": kind},
    )
    token = new_token()
    if kind == "verify_email":
        ttl_sql, ttl = "make_interval(hours => :ttl)", settings.verify_token_ttl_hours
    else:
        ttl_sql, ttl = "make_interval(mins => :ttl)", settings.reset_token_ttl_minutes
    await session.execute(
        text(
            "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
            f"VALUES (:uid, :kind, :hash, now() + {ttl_sql})"
        ),
        {"uid": user_id, "kind": kind, "hash": hash_token(token), "ttl": ttl},
    )
    return token


async def _consume_email_token(session: AsyncSession, token: str, kind: str):  # type: ignore[no-untyped-def]
    """Mark a token used and return its user id. The single UPDATE makes it race-safe:
    two requests with the same token cannot both succeed."""
    user_id = (
        await session.execute(
            text(
                "UPDATE email_tokens SET used_at = now() "
                "WHERE token_hash = :hash AND kind = :kind "
                "AND used_at IS NULL AND expires_at > now() RETURNING user_id"
            ),
            {"hash": hash_token(token), "kind": kind},
        )
    ).scalar_one_or_none()
    if user_id is None:
        raise AppError(
            400, "invalid_token", "This link is invalid or has expired. Please request a new one."
        )
    return user_id


@router.post("/signup", status_code=201, response_model=UserOut)
async def signup(
    body: SignupIn,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    mailer: MailerDep,
    limiter: LimiterDep,
) -> UserOut:
    await limiter.check(f"signup:{client_ip(request)}", 10, 3600)
    password_hash = await hash_password(body.password)
    try:
        async with request.app.state.session_factory() as session, session.begin():
            user_id = (
                await session.execute(
                    text(
                        "INSERT INTO users (email, password_hash, display_name, ui_language) "
                        "VALUES (:email, :ph, :name, :lang) RETURNING id"
                    ),
                    {
                        "email": body.email,
                        "ph": password_hash,
                        "name": body.display_name,
                        "lang": body.ui_language,
                    },
                )
            ).scalar_one()
            session_token = await _create_session(session, user_id, request)
            verify_token = await _issue_email_token(session, user_id, "verify_email")
            user = await _load_user(session, user_id)
    except IntegrityError as exc:
        raise AppError(
            409, "email_taken", "An account with this email already exists. Try signing in."
        ) from exc

    link = f"{get_settings().web_base_url}/verify-email?token={verify_token}"
    subject, text_body = verification_message(link)
    background.add_task(mailer.send, body.email, subject, text_body)
    set_session_cookie(response, session_token)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginIn, request: Request, response: Response, limiter: LimiterDep
) -> UserOut:
    await limiter.check(f"login:ip:{client_ip(request)}", 30, 900)
    await limiter.check(f"login:email:{body.email}", 10, 900)
    invalid = AppError(401, "invalid_credentials", "Email or password is incorrect.")
    async with request.app.state.session_factory() as session, session.begin():
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, password_hash FROM users "
                        "WHERE lower(email) = :email AND status = 'active'"
                    ),
                    {"email": body.email},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            await burn_password_check(body.password)
            raise invalid
        if not await verify_password(row["password_hash"], body.password):
            raise invalid
        token = await _create_session(session, row["id"], request)
        user = await _load_user(session, row["id"])
    set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    """Public on purpose: signing out must work even when the session already expired."""
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        async with request.app.state.session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM sessions WHERE token_hash = :hash"), {"hash": hash_token(token)}
            )
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: AuthUser) -> UserOut:
    return user


@router.post("/verify-email", status_code=204)
async def verify_email(body: TokenIn, request: Request) -> Response:
    """Public so the link works from any browser, including one that is not signed in."""
    async with request.app.state.session_factory() as session, session.begin():
        user_id = await _consume_email_token(session, body.token, "verify_email")
        await session.execute(
            text("UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()) WHERE id = :id"),
            {"id": user_id},
        )
    return Response(status_code=204)


@router.post("/resend-verification", status_code=204)
async def resend_verification(
    user: AuthUser,
    request: Request,
    background: BackgroundTasks,
    mailer: MailerDep,
    limiter: LimiterDep,
) -> Response:
    await limiter.check(f"resend:{user.id}", 3, 3600)
    if user.email_verified:
        return Response(status_code=204)
    async with request.app.state.session_factory() as session, session.begin():
        token = await _issue_email_token(session, user.id, "verify_email")
    link = f"{get_settings().web_base_url}/verify-email?token={token}"
    subject, text_body = verification_message(link)
    background.add_task(mailer.send, user.email, subject, text_body)
    return Response(status_code=204)


@router.post("/forgot-password", status_code=202, response_model=StatusOut)
async def forgot_password(
    body: ForgotIn,
    request: Request,
    background: BackgroundTasks,
    mailer: MailerDep,
    limiter: LimiterDep,
) -> StatusOut:
    """Always answers the same way, so it cannot be used to discover which emails have accounts."""
    await limiter.check(f"forgot:ip:{client_ip(request)}", 10, 3600)
    await limiter.check(f"forgot:email:{body.email}", 3, 3600)
    async with request.app.state.session_factory() as session, session.begin():
        user_id = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = :email AND status = 'active'"),
                {"email": body.email},
            )
        ).scalar_one_or_none()
        if user_id is not None:
            token = await _issue_email_token(session, user_id, "reset_password")
    if user_id is not None:
        link = f"{get_settings().web_base_url}/reset-password?token={token}"
        subject, text_body = reset_message(link)
        background.add_task(mailer.send, body.email, subject, text_body)
    return StatusOut()


@router.post("/reset-password", status_code=204)
async def reset_password(body: ResetIn, request: Request) -> Response:
    password_hash = await hash_password(body.new_password)
    async with request.app.state.session_factory() as session, session.begin():
        user_id = await _consume_email_token(session, body.token, "reset_password")
        await session.execute(
            text(
                "UPDATE users SET password_hash = :ph, updated_at = now(), "
                "email_verified_at = COALESCE(email_verified_at, now()) WHERE id = :id"
            ),
            {"ph": password_hash, "id": user_id},
        )
        # A reset signs the account out everywhere, in case the old password was stolen.
        await session.execute(text("DELETE FROM sessions WHERE user_id = :id"), {"id": user_id})
    return Response(status_code=204)
