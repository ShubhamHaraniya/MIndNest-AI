"""Google OAuth 2.0 (authorization-code flow with PKCE), shared by sign-in and calendar sync.

Nothing here touches the database. The API keeps the short-lived flow state in a signed cookie
(`seal` / `unseal`), so no server-side state is needed between the redirect to Google and the
callback.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
SIGN_IN_SCOPES = "openid email profile"


class GoogleError(Exception):
    """Something went wrong talking to Google, or Google's answer cannot be trusted.

    `permanent` is True when Google itself refused (for example the student removed MindNest in
    their Google account), so asking again cannot help; a network failure is not permanent."""

    def __init__(self, message: str = "", permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


# ------------------------------------------------------------------------------ signed state


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    key = hashlib.sha256(("mindnest-oauth|" + secret).encode("utf-8")).digest()
    return _b64(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def seal(secret: str, data: dict[str, Any], ttl_seconds: int = 600, now: float | None = None) -> str:
    """Pack `data` into a tamper-proof string that stops working after `ttl_seconds`."""
    payload = dict(data, exp=int((now if now is not None else time.time()) + ttl_seconds))
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}"


def unseal(secret: str, blob: str | None, now: float | None = None) -> dict[str, Any] | None:
    """The data from `seal`, or None if it was altered, malformed or has expired."""
    if not blob or blob.count(".") != 1:
        return None
    body, signature = blob.split(".")
    if not hmac.compare_digest(signature, _sign(secret, body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int | float) or exp < (now if now is not None else time.time()):
        return None
    return payload


# ------------------------------------------------------------------------------ the flow


def pkce_pair() -> tuple[str, str]:
    """A random code verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
    nonce: str,
    scope: str = SIGN_IN_SCOPES,
    extra: dict[str, str] | None = None,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        **(extra or {}),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str
    email_verified: bool
    name: str


def profile_from_id_token(
    id_token: str, *, client_id: str, nonce: str, now: float | None = None
) -> GoogleProfile:
    """Read and check the identity token Google returned.

    The token arrives straight from Google's token endpoint over HTTPS, so its signature does not
    need checking again (Google's documented guidance); what must be checked is that it was issued
    by Google, for this app, for this sign-in attempt, and has not expired.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleError("malformed identity token")
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, binascii.Error) as exc:
        raise GoogleError("malformed identity token") from exc
    if not isinstance(claims, dict):
        raise GoogleError("malformed identity token")
    if claims.get("iss") not in ISSUERS:
        raise GoogleError("wrong issuer")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        raise GoogleError("wrong audience")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp < (now if now is not None else time.time()):
        raise GoogleError("identity token expired")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
        claims["nonce"], nonce
    ):
        raise GoogleError("wrong nonce")
    subject, email = claims.get("sub"), claims.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str) or "@" not in email:
        raise GoogleError("identity token has no account")
    verified = claims.get("email_verified")
    return GoogleProfile(
        subject=subject,
        email=email.strip().lower(),
        email_verified=verified is True or verified == "true",
        name=str(claims.get("name") or "").strip(),
    )


class GoogleClient:
    """Talks to Google's token endpoint. Tests replace this class with a fake."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.client_id = client_id
        self._secret = client_secret
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self._secret)

    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        """Trade the one-time code for tokens. Raises GoogleError on any failure."""
        return await self._post(
            TOKEN_URL,
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self._secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._post(
            TOKEN_URL,
            {
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self._secret,
                "grant_type": "refresh_token",
            },
        )

    async def revoke(self, token: str) -> None:
        try:
            await self._http.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass  # best effort: the student disconnected either way

    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.post(url, data=data)
        except httpx.HTTPError as exc:
            raise GoogleError("could not reach Google") from exc
        if response.status_code != 200:
            raise GoogleError(
                f"Google refused the request ({response.status_code})",
                permanent=response.status_code in (400, 401),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise GoogleError("Google sent an unreadable answer") from exc
        if not isinstance(body, dict):
            raise GoogleError("Google sent an unreadable answer")
        return body

    async def aclose(self) -> None:
        await self._http.aclose()
