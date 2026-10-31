"""Encrypting secrets that must be read back later (AI provider keys, Google refresh tokens).

Fernet (AES-128-CBC with an HMAC) from the `cryptography` package. The encryption key is
derived from SECRET_KEY, so a database dump alone cannot be used to read anyone's secrets.
Shared by the API and the calendar MCP server, which both hold SECRET_KEY.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

DEV_SECRET = "dev-only-secret-change-me"


class VaultError(Exception):
    """The secret cannot be read, usually because SECRET_KEY changed after it was saved."""


@lru_cache
def _fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(secret: str, plaintext: str) -> str:
    return _fernet(secret).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(secret: str, ciphertext: str) -> str:
    try:
        return _fernet(secret).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise VaultError("the saved secret can no longer be read") from exc
