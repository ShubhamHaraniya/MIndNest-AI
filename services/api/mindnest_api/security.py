"""Password hashing and opaque tokens.

Passwords use argon2id. Hashing is deliberately slow (tens of milliseconds), so it runs in a
worker thread to keep the event loop free. Session and email tokens are random strings; only
their SHA-256 hash is stored, so a database leak does not reveal a usable token.
"""

import asyncio
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Verified when the email is unknown, so "no such user" and "wrong password" take the same time.
_DUMMY_HASH = _hasher.hash("mindnest-timing-equalizer")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str | None, password: str) -> bool:
    """False for a wrong password and for an account that has none (it signs in with Google);
    both take the same time, so the answer does not reveal which kind of account this is."""
    return await asyncio.to_thread(_verify, password_hash or _DUMMY_HASH, password) and bool(password_hash)


async def burn_password_check(password: str) -> None:
    """Spend the time of a real verification without any user behind it."""
    await asyncio.to_thread(_verify, _DUMMY_HASH, password)


def new_token() -> str:
    """256 bits of randomness, safe for cookies and URLs."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
