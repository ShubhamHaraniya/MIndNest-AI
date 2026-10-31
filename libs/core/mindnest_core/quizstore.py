"""Database steps shared by the API and the worker: finishing an attempt and updating the
student's revision cards from it.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mindnest_core.db import as_json
from mindnest_core.quizlogic import BOX_DAYS, PASS_SCORE, next_review


# Revision cards. One definition of "due" for every screen that counts them (the hub, starting a
# revision round, the results): the card's due day in the student's time zone (bind `:tz`) is today
# or earlier, and its course is not archived. Python twin: `quizlogic.card_is_due`. Statements
# using these must alias the table as `c` (`FROM revision_cards c`).
CARD_LIVE_SQL = (
    "NOT EXISTS (SELECT 1 FROM subjects sb WHERE sb.id = c.subject_id AND sb.archived_at IS NOT NULL)"
)
CARD_DUE_SQL = (
    f"((c.due_at AT TIME ZONE :tz)::date <= (now() AT TIME ZONE :tz)::date AND {CARD_LIVE_SQL})"
)


async def finalize_attempt(session: AsyncSession, attempt_id: UUID, user_id: UUID) -> None:
    """Add up the marks, move the revision cards, and mark the attempt as completed.

    Answers that could not be marked (score is NULL, for example because the AI marker was
    unavailable) are left out of the total and do not move any card.
    """
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.question_id, a.score, q.qtype, q.prompt, q.options, q.answer, "
                    "q.explanation, q.source, q.origin_question_id, z.subject_id, z.language "
                    "FROM quiz_answers a "
                    "JOIN quiz_questions q ON q.id = a.question_id "
                    "JOIN quiz_attempts t ON t.id = a.attempt_id "
                    "JOIN quizzes z ON z.id = t.quiz_id "
                    "WHERE a.attempt_id = :a"
                ),
                {"a": attempt_id},
            )
        )
        .mappings()
        .all()
    )
    points = 0.0
    total = 0
    unscored = 0
    for row in rows:
        if row["score"] is None:
            unscored += 1
            continue
        score = float(row["score"])
        points += score
        total += 1
        await _move_card(session, user_id, row, score)

    await session.execute(
        text(
            "UPDATE quiz_attempts SET status = 'completed', points = :p, total = :t, "
            "unscored = :u, finished_at = now() WHERE id = :a"
        ),
        {"a": attempt_id, "p": points, "t": total, "u": unscored},
    )


async def _move_card(session: AsyncSession, user_id: UUID, row: Any, score: float) -> None:
    origin = row["origin_question_id"] or row["question_id"]
    existing = (
        await session.execute(
            text("SELECT box FROM revision_cards WHERE user_id = :u AND origin_question_id = :o"),
            {"u": user_id, "o": origin},
        )
    ).scalar_one_or_none()
    passed = score >= PASS_SCORE
    box, wait = next_review(int(existing or 1), passed)
    options = as_json(row["options"])
    await session.execute(
        text(
            "INSERT INTO revision_cards (user_id, subject_id, origin_question_id, language, qtype, "
            "prompt, options, answer, explanation, source, box, due_at, times_seen, times_correct, "
            "last_score) VALUES (:u, :s, :o, :lang, :qt, :pr, CAST(:op AS jsonb), :an, :ex, "
            "CAST(:src AS jsonb), :box, now() + make_interval(days => :d), 1, :c, :score) "
            "ON CONFLICT (user_id, origin_question_id) DO UPDATE SET box = :box, "
            "due_at = now() + make_interval(days => :d), times_seen = revision_cards.times_seen + 1, "
            "times_correct = revision_cards.times_correct + :c, last_score = :score, updated_at = now()"
        ),
        {
            "u": user_id, "s": row["subject_id"], "o": origin, "lang": row["language"],
            "qt": row["qtype"], "pr": row["prompt"],
            "op": json.dumps(options) if options is not None else None,
            "an": row["answer"], "ex": row["explanation"],
            "src": json.dumps(as_json(row["source"])) if row["source"] is not None else None,
            "box": box, "d": wait.days, "c": 1 if passed else 0, "score": score,
        },
    )


def interval_days(box: int) -> int:
    return BOX_DAYS[box]
