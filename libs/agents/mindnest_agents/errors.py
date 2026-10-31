"""Provider and agent failures, reduced to short codes that are safe to show a student."""

from typing import Any


class AgentError(Exception):
    """A run failed. `code` is stable and contains no provider text, key or student content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _status_to_code(status: int) -> str:
    if status in (401, 403):
        return "invalid_key"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 413, 422):
        return "bad_request"
    if status >= 500:
        return "provider_unavailable"
    return "provider_error"


KNOWN_CODES = frozenset(
    {"invalid_key", "rate_limited", "bad_request", "provider_unavailable", "provider_error",
     "empty_response", "timeout", "no_key", "unknown_provider"}
)


def error_code(exc: BaseException) -> str:
    """Map any exception raised while calling a provider to one of our stable codes."""
    if isinstance(exc, AgentError):
        return exc.code
    # The app's own provider errors already carry one of the stable codes.
    own = getattr(exc, "code", None)
    if isinstance(own, str) and own in KNOWN_CODES:
        return own
    # Every vendor SDK puts the HTTP status on `status_code`, on `code` (Google) or on `response`.
    for attr in ("status_code", "code"):
        value: Any = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return _status_to_code(value)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return _status_to_code(status)
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "provider_unavailable"
    if "ratelimit" in name:
        return "rate_limited"
    if "authentication" in name or "permissiondenied" in name:
        return "invalid_key"
    if "connection" in name:
        return "provider_unavailable"
    return "provider_error"
