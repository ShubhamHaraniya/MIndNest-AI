from mindnest_api.ratelimit import RedisLimiter
from mindnest_api.security import (
    burn_password_check,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)


async def test_password_round_trip() -> None:
    hashed = await hash_password("a long enough password")
    assert hashed != "a long enough password"
    assert hashed.startswith("$argon2id$")
    assert await verify_password(hashed, "a long enough password")
    assert not await verify_password(hashed, "a different password")


async def test_verify_rejects_garbage_hash_instead_of_raising() -> None:
    assert not await verify_password("not-a-hash", "anything")


async def test_burn_password_check_runs_without_error() -> None:
    await burn_password_check("anything")


def test_tokens_are_unique_and_hash_deterministically() -> None:
    first, second = new_token(), new_token()
    assert first != second
    assert len(first) >= 40
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != hash_token(second)
    assert first not in hash_token(first)


async def test_rate_limiter_fails_open_when_redis_is_down() -> None:
    limiter = RedisLimiter("redis://127.0.0.1:1/0")  # nothing listens on port 1
    try:
        for _ in range(5):
            await limiter.check("test", 1, 60)  # would be over the limit if it counted
    finally:
        await limiter.aclose()
