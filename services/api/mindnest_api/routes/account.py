"""Account security: change password, see and end other sign-ins, download your own data.

Everything here acts on the signed-in user only. Passwords are checked and written through the
same helpers the sign-in routes use; no secret (password hash, session token, provider key)
ever leaves the server in a response.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.deps import AuthUser, LimiterDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.security import hash_password, verify_password

router = APIRouter(prefix="/me", tags=["account"])


class PasswordChangeIn(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Annotated[str, Field(min_length=10, max_length=128)]


class SessionOut(BaseModel):
    id: str
    device: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


class SessionsOut(BaseModel):
    items: list[SessionOut]


class SecurityOut(BaseModel):
    """What the Security tab needs to decide which options to show."""

    has_password: bool
    email_verified: bool


class SignedOutOut(BaseModel):
    signed_out: int


def _device_label(user_agent: str | None) -> str:
    """A short, readable device name. The raw header is long and not meant for people."""
    agent = (user_agent or "").lower()
    if not agent:
        return "unknown"
    browser = "browser"
    # Order matters: Edge and Opera also say "chrome", Chrome also says "safari".
    for needle, name in (
        ("edg/", "Edge"),
        ("opr/", "Opera"),
        ("firefox", "Firefox"),
        ("chrome", "Chrome"),
        ("safari", "Safari"),
    ):
        if needle in agent:
            browser = name
            break
    system = ""
    for needle, name in (
        ("android", "Android"),
        ("iphone", "iPhone"),
        ("ipad", "iPad"),
        ("windows", "Windows"),
        ("mac os", "macOS"),
        ("linux", "Linux"),
    ):
        if needle in agent:
            system = name
            break
    return f"{browser} · {system}" if system else browser


@router.get("/security", response_model=SecurityOut)
async def security_summary(user: AuthUser, request: Request) -> SecurityOut:
    async with request.app.state.session_factory() as session, session.begin():
        has_password = bool(
            (
                await session.execute(
                    text("SELECT password_hash IS NOT NULL FROM users WHERE id = :id"),
                    {"id": user.id},
                )
            ).scalar_one()
        )
    return SecurityOut(has_password=has_password, email_verified=user.email_verified)


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeIn, user: AuthUser, request: Request, limiter: LimiterDep
) -> Response:
    """Change the password and sign out every other device, keeping this one signed in."""
    await limiter.check(f"pwchange:{user.id}", 8, 900)
    if body.new_password == body.current_password:
        raise AppError(
            422, "password_unchanged", "The new password must be different from the current one."
        )
    async with request.app.state.session_factory() as session, session.begin():
        current_hash = (
            await session.execute(
                text("SELECT password_hash FROM users WHERE id = :id"), {"id": user.id}
            )
        ).scalar_one()
        if current_hash is None:
            # A Google-only account has nothing to verify against.
            raise AppError(
                409,
                "no_password_set",
                "This account signs in with Google. Use “Forgot password” on the sign-in page to add one.",
            )
        if not await verify_password(current_hash, body.current_password):
            raise AppError(403, "wrong_password", "The current password is not correct.")
        new_hash = await hash_password(body.new_password)
        await session.execute(
            text("UPDATE users SET password_hash = :ph, updated_at = now() WHERE id = :id"),
            {"ph": new_hash, "id": user.id},
        )
        await session.execute(
            text("DELETE FROM sessions WHERE user_id = :uid AND id <> :sid"),
            {"uid": user.id, "sid": user.session_id},
        )
        # Any unused reset link was issued for the old password; it must not outlive the change.
        await session.execute(
            text(
                "UPDATE email_tokens SET used_at = now() "
                "WHERE user_id = :uid AND kind = 'reset_password' AND used_at IS NULL"
            ),
            {"uid": user.id},
        )
    return Response(status_code=204)


@router.get("/sessions", response_model=SessionsOut)
async def list_sessions(user: AuthUser, request: Request) -> SessionsOut:
    async with request.app.state.session_factory() as session, session.begin():
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, user_agent, created_at, last_seen_at FROM sessions "
                        "WHERE user_id = :uid AND expires_at > now() "
                        "ORDER BY last_seen_at DESC LIMIT 50"
                    ),
                    {"uid": user.id},
                )
            )
            .mappings()
            .all()
        )
    return SessionsOut(
        items=[
            SessionOut(
                id=str(r["id"]),
                device=_device_label(r["user_agent"]),
                created_at=r["created_at"],
                last_seen_at=r["last_seen_at"],
                current=r["id"] == user.session_id,
            )
            for r in rows
        ]
    )


@router.post("/sessions/sign-out-others", response_model=SignedOutOut)
async def sign_out_others(user: AuthUser, request: Request) -> SignedOutOut:
    async with request.app.state.session_factory() as session, session.begin():
        result = await session.execute(
            text("DELETE FROM sessions WHERE user_id = :uid AND id <> :sid"),
            {"uid": user.id, "sid": user.session_id},
        )
    return SignedOutOut(signed_out=int(result.rowcount or 0))  # type: ignore[attr-defined]


@router.get("/export")
async def export_my_data(user: AuthUser, db: UserDbDep, limiter: LimiterDep) -> Response:
    """A JSON copy of the user's own profile, courses and file list.

    File contents, chat history and provider keys are not included: files stay downloadable from
    the library, and keys are write-only by design.
    """
    await limiter.check(f"export:{user.id}", 5, 3600)
    async with db.session() as session:
        subjects = (
            (
                await session.execute(
                    text(
                        "SELECT id, name, course_code, semester, description, archived_at, created_at "
                        "FROM subjects WHERE owner_id = :uid ORDER BY created_at"
                    ),
                    {"uid": user.id},
                )
            )
            .mappings()
            .all()
        )
        materials = (
            (
                await session.execute(
                    text(
                        "SELECT id, subject_id, kind, filename, mime_type, size_bytes, status, created_at "
                        "FROM materials WHERE owner_id = :uid AND deleted_at IS NULL "
                        "ORDER BY created_at"
                    ),
                    {"uid": user.id},
                )
            )
            .mappings()
            .all()
        )

    def plain(row: Mapping[Any, Any]) -> dict[str, Any]:
        """JSON-safe values: dates as ISO text, ids as strings."""
        out: dict[str, Any] = {}
        for raw_key, value in row.items():
            key = str(raw_key)
            if isinstance(value, datetime):
                out[key] = value.isoformat()
            elif value is None or isinstance(value, bool | int | str):
                out[key] = value
            else:
                out[key] = str(value)
        return out

    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "profile": {
            "email": user.email,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "ui_language": user.ui_language,
        },
        "subjects": [plain(r) for r in subjects],
        "materials": [plain(r) for r in materials],
    }
    filename = "mindnest-my-data.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )

