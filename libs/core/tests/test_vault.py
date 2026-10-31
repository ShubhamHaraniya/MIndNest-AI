"""Encrypting saved keys and Google tokens."""

import pytest
from mindnest_core.vault import VaultError, decrypt, encrypt


def test_it_round_trips_and_does_not_leak():
    sealed = encrypt("s" * 40, "1//refresh-token")
    assert "refresh-token" not in sealed and decrypt("s" * 40, sealed) == "1//refresh-token"


def test_the_wrong_key_or_garbage_says_the_value_is_unreadable():
    sealed = encrypt("s" * 40, "x")
    with pytest.raises(VaultError):
        decrypt("t" * 40, sealed)
    with pytest.raises(VaultError):
        decrypt("s" * 40, "not a token")
