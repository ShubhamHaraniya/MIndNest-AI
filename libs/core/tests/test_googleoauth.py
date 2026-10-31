"""Google OAuth helpers that need no database or network."""

import asyncio
import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mindnest_core.googleoauth import (
    GoogleClient,
    GoogleError,
    authorize_url,
    pkce_pair,
    profile_from_id_token,
    seal,
    unseal,
)

CLIENT = "app.apps.googleusercontent.com"
NOW = 1_800_000_000.0


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(**override: Any) -> str:
    claims: dict[str, Any] = {
        "iss": "accounts.google.com", "aud": CLIENT, "sub": "1234", "email": "Asha@Example.com",
        "email_verified": True, "name": "Asha", "nonce": "n1", "exp": NOW + 600,
    }
    claims.update(override)
    return f"{b64(b'{}')}.{b64(json.dumps(claims).encode())}.sig"


# ------------------------------------------------------------------------------ signed state


def test_sealed_data_comes_back_intact():
    blob = seal("secret", {"a": 1, "b": "x"}, now=NOW)
    data = unseal("secret", blob, now=NOW + 10)
    assert data is not None and data["a"] == 1 and data["b"] == "x"


def test_sealed_data_fails_when_changed_expired_or_opened_with_another_secret():
    blob = seal("secret", {"a": 1}, ttl_seconds=60, now=NOW)
    body, signature = blob.split(".")
    forged = b64(json.dumps({"a": 2, "exp": NOW + 999}).encode()) + "." + signature
    assert unseal("secret", forged, now=NOW) is None
    assert unseal("other", blob, now=NOW) is None
    assert unseal("secret", blob, now=NOW + 61) is None
    for junk in (None, "", "nodots", "a.b.c", "!!!.???"):
        assert unseal("secret", junk, now=NOW) is None


# ------------------------------------------------------------------------------ the flow


def test_pkce_challenge_matches_its_verifier_and_is_never_reused():
    verifier, challenge = pkce_pair()
    assert challenge == b64(hashlib.sha256(verifier.encode()).digest())
    assert len(verifier) >= 43 and pkce_pair()[0] != verifier


def test_the_authorize_url_carries_everything_google_needs():
    url = authorize_url(client_id="c", redirect_uri="https://x/cb", state="s", challenge="h", nonce="n")
    query = parse_qs(urlparse(url).query)
    assert query["state"] == ["s"] and query["nonce"] == ["n"] and query["code_challenge"] == ["h"]
    assert query["redirect_uri"] == ["https://x/cb"] and query["response_type"] == ["code"]


# ------------------------------------------------------------------------------ the identity token


def test_a_good_token_gives_a_profile_with_a_lowercase_email():
    profile = profile_from_id_token(token(), client_id=CLIENT, nonce="n1", now=NOW)
    assert profile.subject == "1234" and profile.email == "asha@example.com"
    assert profile.email_verified is True and profile.name == "Asha"


def test_both_google_issuer_spellings_and_a_list_of_audiences_are_accepted():
    for iss in ("accounts.google.com", "https://accounts.google.com"):
        assert profile_from_id_token(token(iss=iss), client_id=CLIENT, nonce="n1", now=NOW)
    assert profile_from_id_token(token(aud=["x", CLIENT]), client_id=CLIENT, nonce="n1", now=NOW)


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "https://evil.example"}, {"aud": "other"}, {"nonce": "n2"}, {"nonce": None},
        {"exp": NOW - 1}, {"exp": "soon"}, {"sub": ""}, {"email": "not-an-email"}, {"email": None},
    ],
)
def test_a_token_that_does_not_check_out_is_refused(override):
    with pytest.raises(GoogleError):
        profile_from_id_token(token(**override), client_id=CLIENT, nonce="n1", now=NOW)


def test_rubbish_is_refused_not_crashed_on():
    for junk in ("", "a.b", "a.b.c", "a.!!!.c", f"a.{b64(b'[1]')}.c"):
        with pytest.raises(GoogleError):
            profile_from_id_token(junk, client_id=CLIENT, nonce="n1", now=NOW)


def test_unverified_email_is_reported_as_unverified():
    assert profile_from_id_token(
        token(email_verified=False), client_id=CLIENT, nonce="n1", now=NOW
    ).email_verified is False
    assert profile_from_id_token(
        token(email_verified="true"), client_id=CLIENT, nonce="n1", now=NOW
    ).email_verified is True
    assert profile_from_id_token(
        token(email_verified="yes"), client_id=CLIENT, nonce="n1", now=NOW
    ).email_verified is False


# ------------------------------------------------------------------------------ the HTTP client


def make_client(handler) -> GoogleClient:  # type: ignore[no-untyped-def]
    return GoogleClient("id", "secret", transport=httpx.MockTransport(handler))


def test_the_code_exchange_sends_the_verifier_and_secret():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"id_token": "t", "access_token": "a"})

    result = asyncio.run(make_client(handler).exchange_code("the-code", "the-verifier", "https://x/cb"))
    assert result["id_token"] == "t"
    assert seen["code"] == "the-code" and seen["code_verifier"] == "the-verifier"
    assert seen["client_secret"] == "secret" and seen["grant_type"] == "authorization_code"


def test_google_errors_become_google_error():
    for response in (httpx.Response(400, json={"error": "invalid_grant"}),
                     httpx.Response(200, text="not json"), httpx.Response(200, json=[1])):
        client = make_client(lambda _request, r=response: r)
        with pytest.raises(GoogleError):
            asyncio.run(client.exchange_code("c", "v", "u"))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    with pytest.raises(GoogleError):
        asyncio.run(make_client(down).exchange_code("c", "v", "u"))


def test_refresh_and_revoke():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    client = make_client(handler)
    assert asyncio.run(client.refresh("r"))["access_token"] == "new"
    asyncio.run(client.revoke("r"))
    assert len(calls) == 2 and calls[1].endswith("/revoke")
