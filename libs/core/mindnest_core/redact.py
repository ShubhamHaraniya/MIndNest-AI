"""Keeping secrets out of logs, stored errors and evaluation output.

Provider API keys are only ever held in memory for the length of one call. This module is the
second line of defence: anything that might be logged or stored passes through `redact`, which
removes the exact keys in use and anything shaped like a well-known provider key.
"""

import logging
import re
from collections.abc import Iterable

REDACTED = "[redacted]"

# Shapes of real provider keys. Deliberately generous: a false positive only hides a few
# characters of a log line, a false negative leaks a key.
_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)((?:x-api-key|x-goog-api-key|api[_-]?key)['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._\-]{8,}"),
]


# Public name for other modules (personal-data masking reuses these shapes).
SECRET_PATTERNS = _PATTERNS


def redact(text: str, known: Iterable[str] = ()) -> str:
    for secret in known:
        if secret and len(secret) >= 6:
            text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs every record that passes through a handler, including exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a broken format string must not hide the record
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None and not record.exc_text:
            record.exc_text = redact(
                "".join(logging.Formatter().formatException(record.exc_info))
            )
        return True
