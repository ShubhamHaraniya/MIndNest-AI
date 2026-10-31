import asyncio

from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings
from sqlalchemy import text

KEY = "sk-test-1234567890abcdef"


def _save(user, provider="openai", **body):  # type: ignore[no-untyped-def]
    return user.request("PUT", f"/settings/providers/{provider}", json={"api_key": KEY, **body})


def _stored_ciphertext(email: str, provider: str) -> str:
    async def go() -> str:
        engine = make_engine(get_settings().migration_database_url)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(
                    text(
                        "SELECT k.ciphertext FROM provider_keys k JOIN users u ON u.id = k.user_id "
                        "WHERE u.email = :e AND k.provider = :p"
                    ),
                    {"e": email, "p": provider},
                )
                return str(row.scalar_one())
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_new_user_sees_four_unconfigured_providers(make_user):  # type: ignore[no-untyped-def]
    listing = make_user().get("/settings/providers").json()
    assert [p["id"] for p in listing] == ["anthropic", "gemini", "openai", "groq"]
    assert all(not p["configured"] and p["key_hint"] is None for p in listing)
    assert all(p["models"] and p["default_model"] for p in listing)


def test_saved_key_is_encrypted_and_never_returned(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    saved = _save(user, model="gpt-4o")
    assert saved.status_code == 200, saved.text
    assert KEY not in saved.text
    assert saved.json()["configured"] is True
    assert saved.json()["key_hint"] == KEY[-4:]
    assert saved.json()["model"] == "gpt-4o"

    listing = user.get("/settings/providers")
    assert KEY not in listing.text
    openai = next(p for p in listing.json() if p["id"] == "openai")
    assert openai["configured"] and openai["key_hint"] == "cdef"

    stored = _stored_ciphertext(user.email, "openai")
    assert KEY not in stored and stored.startswith("gAAAA")


def test_changing_only_the_model_keeps_the_key(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    _save(user)
    changed = user.request("PUT", "/settings/providers/openai", json={"model": "gpt-4o"})
    assert changed.status_code == 200
    assert changed.json()["model"] == "gpt-4o" and changed.json()["key_hint"] == "cdef"
    assert user.post("/settings/providers/openai/test").status_code == 200
    assert llm.calls[-1]["api_key"] == KEY and llm.calls[-1]["model"] == "gpt-4o"


def test_validation(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    no_key = user.request("PUT", "/settings/providers/groq", json={"model": "x"})
    assert no_key.status_code == 422
    assert _save(user, "groq", model="bad model name!").status_code == 422
    short = user.request("PUT", "/settings/providers/groq", json={"api_key": "short"})
    assert short.status_code == 422
    assert user.request("PUT", "/settings/providers/nope", json={"api_key": KEY}).status_code == 422


def test_delete_removes_the_key(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    _save(user, "gemini")
    assert user.delete("/settings/providers/gemini").status_code == 204
    assert user.delete("/settings/providers/gemini").status_code == 204
    gemini = next(p for p in user.get("/settings/providers").json() if p["id"] == "gemini")
    assert gemini["configured"] is False


def test_keys_are_private_to_their_owner(make_user):  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    _save(alice, "anthropic")
    assert all(not p["configured"] for p in bob.get("/settings/providers").json())
    assert bob.post("/settings/providers/anthropic/test").status_code == 404


def test_key_test_reports_provider_errors(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.post("/settings/providers/openai/test").status_code == 404
    _save(user)
    assert user.post("/settings/providers/openai/test").json() == {"ok": True}
    llm.error = "invalid_key"
    failed = user.post("/settings/providers/openai/test")
    assert failed.status_code == 400 and failed.json()["code"] == "llm_invalid_key"


def test_models_are_listed_from_the_provider_with_the_saved_key(make_user, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.get("/settings/providers/groq/models").status_code == 404
    _save(user, "groq")
    listing = user.get("/settings/providers/groq/models")
    assert listing.status_code == 200 and listing.json() == {"models": ["model-a", "model-b"]}
    llm.error = "invalid_key"
    failed = user.get("/settings/providers/groq/models")
    assert failed.status_code == 400 and failed.json()["code"] == "llm_invalid_key"
    assert make_user().get("/settings/providers/groq/models").status_code == 404
