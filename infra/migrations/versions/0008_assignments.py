"""Assignments and the AI help runs on them (per student).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Row-level security on user_id, like every other student table. An assignment keeps working
# if its subject is deleted (subject_id becomes NULL), and the planner reads due_at later.
UPGRADE = [
    """
    CREATE TABLE assignments (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      title text NOT NULL,
      brief text NOT NULL DEFAULT '',
      draft text NOT NULL DEFAULT '',
      due_at timestamptz,
      status text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX assignments_user_idx ON assignments (user_id, due_at NULLS LAST)",
    """
    CREATE TABLE assignment_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      assignment_id uuid NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      kind text NOT NULL CHECK (kind IN ('breakdown', 'outline', 'feedback')),
      language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'hi', 'gu')),
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'ready', 'failed')),
      error text,
      result text,
      sources jsonb NOT NULL DEFAULT '[]'::jsonb,
      config jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz
    )
    """,
    "CREATE INDEX assignment_runs_assignment_idx ON assignment_runs (assignment_id, created_at DESC)",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON assignments, assignment_runs TO mindnest_app",
]

_TABLES = ("assignments", "assignment_runs")
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
