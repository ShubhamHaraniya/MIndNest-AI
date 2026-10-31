"""The signed-in user's own profile and onboarding progress."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.schemas import USER_COLUMNS, Language, UserOut

router = APIRouter(tags=["me"])


class MeUpdate(BaseModel):
    """Only the fields that are present are changed. answer_language may be null, which means
    "reply in the language of the question"."""

    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    timezone: Annotated[str, Field(max_length=64)] | None = None
    ui_language: Language | None = None
    answer_language: Language | None = None
    onboarding_step: Annotated[int, Field(ge=0, le=5)] | None = None
    onboarding_completed: bool | None = None
    mask_personal_data: bool | None = None
    institution_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


_NULLABLE = {"answer_language"}


@router.patch("/me", response_model=UserOut)
async def update_me(body: MeUpdate, user: AuthUser, db: UserDbDep) -> UserOut:
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None and key not in _NULLABLE:
            raise AppError(422, "validation_error", f"{key} cannot be null.")
    if "institution_name" in changes:
        # Collapse runs of spaces so "IIT  Delhi" and "IIT Delhi" are one college.
        changes["institution_name"] = " ".join(str(changes["institution_name"]).split())
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise AppError(422, "invalid_timezone", "Unknown timezone.") from exc
    if not changes:
        return user

    assignments: list[str] = []
    params: dict[str, object] = {"id": user.id}
    columns = (
        "display_name",
        "timezone",
        "ui_language",
        "answer_language",
        "onboarding_step",
        "mask_personal_data",
        "institution_name",
    )
    for column in columns:
        if column in changes:
            assignments.append(f"{column} = :{column}")
            params[column] = changes[column]
    if "onboarding_completed" in changes:
        assignments.append(
            "onboarding_completed_at = COALESCE(onboarding_completed_at, now())"
            if changes["onboarding_completed"]
            else "onboarding_completed_at = NULL"
        )
    assignments.append("updated_at = now()")

    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        f"UPDATE users u SET {', '.join(assignments)} "
                        f"WHERE u.id = :id RETURNING {USER_COLUMNS}"
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
    return UserOut(**row)
