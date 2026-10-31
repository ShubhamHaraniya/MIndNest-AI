"""Short-lived, single-purpose tokens the API hands to the calendar MCP server.

Every call to the calendar server carries its own token. The token says WHO (the student), WHAT
(one tool) and, by a hash, exactly WHICH arguments, and it stops working after about a minute. So a
token that leaks, or a server that is tricked, cannot be used to read someone else's calendar, to
call a different tool, or to change the arguments the student approved.

A token is `<payload>.<signature>`: the payload is JSON in base64url, the signature is HMAC-SHA256
over it. The key is derived from SECRET_KEY with its own label, so it is never the same key that
encrypts stored secrets or signs cookies.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

AUDIENCE = "mindnest-calendar-mcp"
DEFAULT_TTL = 60.0
MAX_TTL = 300.0


class TokenError(Exception):
    """The token is missing, forged, expired, for another tool, or already used."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Claims:
    user_id: str
    tool: str
    args_hash: str
    expires_at: float
    token_id: str


def _key(secret_key: str) -> bytes:
    return hmac.new(secret_key.encode("utf-8"), b"mindnest/calendar-mcp/v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def args_hash(args: Mapping[str, Any]) -> str:
    """A fingerprint of a tool's arguments. Both sides compute it from the same JSON-able values."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mint(
    secret_key: str, user_id: str, tool: str, args: Mapping[str, Any], *, ttl: float = DEFAULT_TTL,
    now: float | None = None,
) -> str:
    issued = time.time() if now is None else now
    payload = {
        "aud": AUDIENCE, "sub": str(user_id), "tool": tool, "h": args_hash(args),
        "exp": issued + min(max(ttl, 1.0), MAX_TTL), "jti": secrets.token_hex(8),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_key(secret_key), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify(secret_key: str, token: str | None, *, now: float | None = None) -> Claims:
    """Check the signature, the audience and the expiry. Which tool and arguments it is for is
    checked separately, by `check_call`, once the server knows them."""
    if not token or token.count(".") != 1:
        raise TokenError("missing_token")
    body, _, signature = token.partition(".")
    try:
        expected = _b64(hmac.new(_key(secret_key), body.encode("ascii"), hashlib.sha256).digest())
    except UnicodeEncodeError as exc:
        raise TokenError("bad_token") from exc
    if not hmac.compare_digest(signature, expected):
        raise TokenError("bad_token")
    try:
        data = json.loads(_unb64(body))
        claims = Claims(str(data["sub"]), str(data["tool"]), str(data["h"]), float(data["exp"]), str(data["jti"]))
        audience = data["aud"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("bad_token") from exc
    if audience != AUDIENCE:
        raise TokenError("bad_token")
    if (time.time() if now is None else now) >= claims.expires_at:
        raise TokenError("expired_token")
    return claims


def check_call(claims: Claims, tool: str, args: Mapping[str, Any]) -> None:
    """The token must be for exactly this tool and exactly these arguments."""
    if claims.tool != tool:
        raise TokenError("wrong_tool")
    if not hmac.compare_digest(claims.args_hash, args_hash(args)):
        raise TokenError("wrong_arguments")


class ReplayGuard:
    """Remembers token ids already used, so one token works once. Kept in memory: with several
    server copies a token could be replayed once per copy within its minute, which the argument
    hash and the event id (see create_event) still make harmless."""

    def __init__(self, max_items: int = 5000) -> None:
        self._seen: dict[str, float] = {}
        self._max = max_items

    def use(self, claims: Claims, *, now: float | None = None) -> None:
        moment = time.time() if now is None else now
        if len(self._seen) >= self._max:
            self._seen = {k: v for k, v in self._seen.items() if v > moment}
            if len(self._seen) >= self._max:
                raise TokenError("busy")
        if claims.token_id in self._seen:
            raise TokenError("replayed_token")
        self._seen[claims.token_id] = claims.expires_at
