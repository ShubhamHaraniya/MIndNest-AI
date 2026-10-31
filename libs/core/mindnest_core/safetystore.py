"""Writing the safety log. Only kinds and counts are stored, never the text itself."""

import json
import logging
from collections import Counter
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mindnest.safety")

# Kinds that go in security_events.kind
PII_MASKED = "pii_masked"
INJECTION_IN_SOURCE = "injection_in_source"
HIDDEN_CHARS = "hidden_characters"
OUTPUT_CLEANED = "output_cleaned"
OUTPUT_BLOCKED = "output_blocked"
# Guardrails (NeMo rails). `detail` holds the rail, the labels and the timing, never the text.
GUARD_BLOCKED = "guardrail_blocked"
GUARD_CLEANED = "guardrail_cleaned"
GUARD_REVIEWED = "guardrail_reviewed"


async def record_event(
    session: AsyncSession, user_id: UUID, kind: str, source: str, detail: Mapping[str, object]
) -> None:
    """Add one line to the student's safety log. Logging must never break the request."""
    try:
        await session.execute(
            text(
                "INSERT INTO security_events (user_id, kind, source, detail) "
                "VALUES (:u, :k, :s, CAST(:d AS jsonb))"
            ),
            {"u": user_id, "k": kind, "s": source, "d": json.dumps(dict(detail))},
        )
    except Exception:  # pragma: no cover - the log is best effort
        logger.warning("Could not write a safety event (%s)", kind)


async def record_prepared(
    session: AsyncSession, user_id: UUID, source: str, *, pii: Counter[str], injections: int, hidden: int
) -> None:
    """One call for everything found while preparing text for an AI provider."""
    if pii:
        await record_event(session, user_id, PII_MASKED, source, dict(pii))
    if injections:
        await record_event(session, user_id, INJECTION_IN_SOURCE, source, {"phrases": injections})
    if hidden:
        await record_event(session, user_id, HIDDEN_CHARS, source, {"characters": hidden})
