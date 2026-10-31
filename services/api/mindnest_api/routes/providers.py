"""Settings: the AI provider keys a student brings (bring your own key)."""

import re
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Response
from mindnest_core.settings import get_settings
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text

from mindnest_api.deps import AuthUser, LimiterDep, LLMDep, UserDbDep
from mindnest_api.errors import AppError
from mindnest_api.llm import PROVIDERS, ChatMessage, LLMError, ProviderId
from mindnest_api.vault import decrypt, encrypt, key_hint

router = APIRouter(prefix="/settings/providers", tags=["settings"])

MODEL_NAME = re.compile(r"^[\w.:/\-]{1,100}$")

ApiKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=400)]


class ProviderOut(BaseModel):
    id: ProviderId
    label: str
    models: list[str]
    default_model: str
    key_url: str
    configured: bool
    key_hint: str | None
    # The model chosen in Settings; null means the provider's default is used.
    model: str | None


class ProviderIn(BaseModel):
    # Omit to keep the saved key and only change the model.
    api_key: ApiKey | None = None
    model: str | None = None


def _out(provider_id: str, row: dict | None) -> ProviderOut:  # type: ignore[type-arg]
    info = PROVIDERS[provider_id]
    return ProviderOut(
        id=info.id,
        label=info.label,
        models=list(info.models),
        default_model=info.default_model,
        key_url=info.key_url,
        configured=row is not None,
        key_hint=row["key_hint"] if row else None,
        model=row["model"] if row else None,
    )


@router.get("", response_model=list[ProviderOut])
async def list_providers(_user: AuthUser, db: UserDbDep) -> list[ProviderOut]:
    async with db.session() as session:
        rows = (
            (await session.execute(text("SELECT provider, key_hint, model FROM provider_keys")))
            .mappings()
            .all()
        )
    saved = {row["provider"]: dict(row) for row in rows}
    return [_out(provider_id, saved.get(provider_id)) for provider_id in PROVIDERS]


@router.put("/{provider}", response_model=ProviderOut)
async def save_provider(
    provider: ProviderId, body: ProviderIn, user: AuthUser, db: UserDbDep
) -> ProviderOut:
    model = (body.model or "").strip() or None
    if model is not None and not MODEL_NAME.match(model):
        raise AppError(422, "validation_error", "That model name is not valid.")

    async with db.session() as session:
        existing = (
            await session.execute(
                text("SELECT 1 FROM provider_keys WHERE provider = :p"), {"p": provider}
            )
        ).scalar_one_or_none()
        if body.api_key is None:
            if existing is None:
                raise AppError(422, "validation_error", "An API key is required.")
            await session.execute(
                text("UPDATE provider_keys SET model = :m, updated_at = now() WHERE provider = :p"),
                {"m": model, "p": provider},
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO provider_keys (user_id, provider, ciphertext, key_hint, model) "
                    "VALUES (:u, :p, :c, :h, :m) "
                    "ON CONFLICT (user_id, provider) DO UPDATE SET ciphertext = :c, key_hint = :h, "
                    "model = :m, updated_at = now()"
                ),
                {
                    "u": user.id,
                    "p": provider,
                    "c": encrypt(get_settings().secret_key, body.api_key),
                    "h": key_hint(body.api_key),
                    "m": model,
                },
            )
        row = (
            (
                await session.execute(
                    text("SELECT key_hint, model FROM provider_keys WHERE provider = :p"),
                    {"p": provider},
                )
            )
            .mappings()
            .one()
        )
    return _out(provider, dict(row))


@router.delete("/{provider}", status_code=204)
async def delete_provider(provider: ProviderId, _user: AuthUser, db: UserDbDep) -> Response:
    async with db.session() as session:
        await session.execute(text("DELETE FROM provider_keys WHERE provider = :p"), {"p": provider})
    return Response(status_code=204)


class KeyTestResult(BaseModel):
    ok: bool


@router.post("/{provider}/test", response_model=KeyTestResult)
async def test_provider(
    provider: ProviderId, user: AuthUser, db: UserDbDep, llm: LLMDep, limiter: LimiterDep
) -> KeyTestResult:
    """Sends one tiny message with the saved key, so a typo shows up here and not mid-chat."""
    await limiter.check(f"keytest:{user.id}", 10, 600)
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text("SELECT ciphertext, model FROM provider_keys WHERE provider = :p"),
                    {"p": provider},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise AppError(404, "not_found", "No key is saved for this provider.")
    api_key = decrypt(get_settings().secret_key, row["ciphertext"])
    model = row["model"] or PROVIDERS[provider].default_model
    try:
        stream = llm.stream(
            provider, api_key, model, "Reply with the single word OK.", [ChatMessage("user", "Hi")]
        )
        async with aclosing(stream) as pieces:
            async for _piece in pieces:
                break
    except LLMError as exc:
        raise AppError(400, f"llm_{exc.code}", "The provider rejected the test request.") from exc
    return KeyTestResult(ok=True)


class ModelList(BaseModel):
    models: list[str]


@router.get("/{provider}/models", response_model=ModelList)
async def list_provider_models(
    provider: ProviderId, user: AuthUser, db: UserDbDep, llm: LLMDep, limiter: LimiterDep
) -> ModelList:
    """The models this student's saved key can actually use, asked of the provider itself."""
    await limiter.check(f"models:{user.id}", 30, 600)
    async with db.session() as session:
        ciphertext = (
            await session.execute(
                text("SELECT ciphertext FROM provider_keys WHERE provider = :p"), {"p": provider}
            )
        ).scalar_one_or_none()
    if ciphertext is None:
        raise AppError(404, "not_found", "No key is saved for this provider.")
    try:
        found = await llm.list_models(provider, decrypt(get_settings().secret_key, ciphertext))
    except LLMError as exc:
        raise AppError(400, f"llm_{exc.code}", "The provider could not list its models.") from exc
    return ModelList(models=found)
