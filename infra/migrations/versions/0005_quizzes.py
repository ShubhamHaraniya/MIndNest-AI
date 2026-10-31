"""Quizzes, attempts and the spaced-revision cards (per student).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Same rule as every other student table: row-level security on user_id, so a student only ever
# sees their own quizzes and cards. Revision cards keep a copy of the question, so deleting a quiz
# never removes what the student still has to revise.
UPGRADE = [
    """
    CREATE TABLE quizzes (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      title text NOT NULL,
      source text NOT NULL DEFAULT 'subject' CHECK (source IN ('subject', 'revision')),
      language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'hi', 'gu')),
      config jsonb NOT NULL DEFAULT '{}'::jsonb,
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'generating', 'ready', 'failed')),
      error text,
      question_count integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz
    )
    """,
    "CREATE INDEX quizzes_user_idx ON quizzes (user_id, created_at DESC)",
    """
    CREATE TABLE quiz_questions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      quiz_id uuid NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      position integer NOT NULL,
      qtype text NOT NULL CHECK (qtype IN ('mcq', 'true_false', 'short')),
      prompt text NOT NULL,
      options jsonb,
      answer text NOT NULL,
      explanation text,
      source jsonb,
      origin_question_id uuid,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (quiz_id, position)
    )
    """,
    """
    CREATE TABLE quiz_attempts (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      quiz_id uuid NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      status text NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'grading', 'completed')),
      points numeric NOT NULL DEFAULT 0,
      total integer NOT NULL DEFAULT 0,
      unscored integer NOT NULL DEFAULT 0,
      started_at timestamptz NOT NULL DEFAULT now(),
      submitted_at timestamptz,
      finished_at timestamptz
    )
    """,
    "CREATE INDEX quiz_attempts_user_idx ON quiz_attempts (user_id, finished_at DESC)",
    "CREATE INDEX quiz_attempts_quiz_idx ON quiz_attempts (quiz_id)",
    """
    CREATE TABLE quiz_answers (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      attempt_id uuid NOT NULL REFERENCES quiz_attempts (id) ON DELETE CASCADE,
      question_id uuid NOT NULL REFERENCES quiz_questions (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      response text NOT NULL DEFAULT '',
      score numeric,
      feedback text,
      UNIQUE (attempt_id, question_id)
    )
    """,
    """
    CREATE TABLE revision_cards (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      origin_question_id uuid NOT NULL,
      language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'hi', 'gu')),
      qtype text NOT NULL CHECK (qtype IN ('mcq', 'true_false', 'short')),
      prompt text NOT NULL,
      options jsonb,
      answer text NOT NULL,
      explanation text,
      source jsonb,
      box integer NOT NULL DEFAULT 1 CHECK (box BETWEEN 1 AND 5),
      due_at timestamptz NOT NULL DEFAULT now(),
      times_seen integer NOT NULL DEFAULT 0,
      times_correct integer NOT NULL DEFAULT 0,
      last_score numeric,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (user_id, origin_question_id)
    )
    """,
    "CREATE INDEX revision_cards_due_idx ON revision_cards (user_id, due_at)",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON quizzes, quiz_questions, quiz_attempts, quiz_answers, "
    "revision_cards TO mindnest_app",
]

_TABLES = ("quizzes", "quiz_questions", "quiz_attempts", "quiz_answers", "revision_cards")
for _table in _TABLES:
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

DOWNGRADE = [f"DROP TABLE IF EXISTS {t}" for t in reversed(_TABLES)]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
