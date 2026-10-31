"""Exams, study tasks and planner preferences (per student).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# Dates are plain calendar dates in the student's own time zone (users.timezone). A study task
# made by the planner keeps a template + params next to its English title, so the web app can show
# it in the student's language. Generating a plan again replaces only planner-made, unfinished
# tasks from today on; finished tasks and tasks the student added are never touched.
UPGRADE = [
    """
    CREATE TABLE exams (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      title text NOT NULL,
      exam_on date NOT NULL,
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX exams_user_idx ON exams (user_id, exam_on)",
    """
    CREATE TABLE study_tasks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      assignment_id uuid REFERENCES assignments (id) ON DELETE CASCADE,
      exam_id uuid REFERENCES exams (id) ON DELETE CASCADE,
      kind text NOT NULL DEFAULT 'custom' CHECK (kind IN ('revise', 'assignment', 'quiz', 'custom')),
      source text NOT NULL DEFAULT 'manual' CHECK (source IN ('plan', 'manual')),
      title text NOT NULL,
      template text,
      params jsonb NOT NULL DEFAULT '{}'::jsonb,
      planned_for date NOT NULL,
      minutes integer NOT NULL DEFAULT 30 CHECK (minutes BETWEEN 5 AND 480),
      status text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'done', 'skipped')),
      created_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz
    )
    """,
    "CREATE INDEX study_tasks_user_idx ON study_tasks (user_id, planned_for)",
    """
    CREATE TABLE study_preferences (
      user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
      daily_minutes integer NOT NULL DEFAULT 90 CHECK (daily_minutes BETWEEN 20 AND 480),
      days_off integer[] NOT NULL DEFAULT '{}',
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON exams, study_tasks, study_preferences TO mindnest_app",
]

_TABLES = ("exams", "study_tasks", "study_preferences")
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
