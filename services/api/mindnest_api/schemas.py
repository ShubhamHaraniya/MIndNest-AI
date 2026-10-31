"""Request and response shapes shared by several routes."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr

Language = Literal["en", "hi", "gu"]
Email = Annotated[EmailStr, AfterValidator(lambda value: value.strip().lower())]


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    email_verified: bool
    timezone: str
    ui_language: Language
    answer_language: Language | None
    onboarding_step: int
    onboarding_completed: bool
    mask_personal_data: bool
    is_admin: bool = False
    # Self-declared; "My college" in the Materials Library is everyone who typed the same name.
    institution_name: str = ""


# Column list that maps one-to-one onto UserOut. The table must be aliased as "u".
USER_COLUMNS = """
  u.id, u.email, u.display_name, (u.email_verified_at IS NOT NULL) AS email_verified,
  u.timezone, u.ui_language, u.answer_language, u.onboarding_step,
  (u.onboarding_completed_at IS NOT NULL) AS onboarding_completed,
  u.mask_personal_data, u.is_admin, u.institution_name
"""
