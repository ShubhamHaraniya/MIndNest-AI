"""Encrypting the AI provider keys and Google tokens users save.

The work is done in mindnest_core.vault (shared with the calendar MCP server); this module turns
its error into the API's own error type.
"""

from mindnest_core.vault import DEV_SECRET, VaultError
from mindnest_core.vault import decrypt as _decrypt
from mindnest_core.vault import encrypt as _encrypt

from mindnest_api.errors import AppError

__all__ = ["DEV_SECRET", "decrypt", "encrypt", "key_hint"]


def encrypt(secret: str, plaintext: str) -> str:
    return _encrypt(secret, plaintext)


def decrypt(secret: str, ciphertext: str) -> str:
    try:
        return _decrypt(secret, ciphertext)
    except VaultError as exc:
        # Happens when SECRET_KEY changed after the key was saved.
        raise AppError(
            409, "key_unreadable", "The saved key can no longer be read. Please save it again."
        ) from exc


def key_hint(api_key: str) -> str:
    return api_key[-4:]
