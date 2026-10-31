"""Evaluation Lab: datasets of questions, runs, and per-question results (per student).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# These tables live in the public schema with the same row-level security as every other student
# table, so an evaluation only ever searches the signed-in student's own materials. (The separate
# `eval` schema from 0001 is kept for later developer-wide suites and is not used here.)
UPGRADE = [
    """
    CREATE TABLE eval_datasets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      name text NOT NULL,
      description text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (user_id, name)
    )
    """,
    """
    CREATE TABLE eval_cases (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_id uuid NOT NULL REFERENCES eval_datasets (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      case_key text NOT NULL,
      language text NOT NULL CHECK (language IN ('en', 'hi', 'gu')),
      question text NOT NULL,
      reference_answer text,
      answerable boolean NOT NULL DEFAULT true,
      evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
      tags text[] NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (dataset_id, case_key)
    )
    """,
    "CREATE INDEX eval_cases_dataset_idx ON eval_cases (dataset_id)",
    """
    CREATE TABLE eval_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      dataset_id uuid NOT NULL REFERENCES eval_datasets (id) ON DELETE CASCADE,
      label text,
      config jsonb NOT NULL,
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
      total integer NOT NULL DEFAULT 0,
      done integer NOT NULL DEFAULT 0,
      summary jsonb,
      error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz,
      finished_at timestamptz
    )
    """,
    "CREATE INDEX eval_runs_user_idx ON eval_runs (user_id, created_at DESC)",
    """
    CREATE TABLE eval_results (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      run_id uuid NOT NULL REFERENCES eval_runs (id) ON DELETE CASCADE,
      case_id uuid NOT NULL REFERENCES eval_cases (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      retrieved jsonb NOT NULL DEFAULT '[]'::jsonb,
      answer text,
      scores jsonb NOT NULL DEFAULT '{}'::jsonb,
      timings jsonb NOT NULL DEFAULT '{}'::jsonb,
      error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (run_id, case_id)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON eval_datasets, eval_cases, eval_runs, eval_results TO mindnest_app",
]

for _table in ("eval_datasets", "eval_cases", "eval_runs", "eval_results"):
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

DOWNGRADE = [
    "DROP TABLE IF EXISTS eval_results",
    "DROP TABLE IF EXISTS eval_runs",
    "DROP TABLE IF EXISTS eval_cases",
    "DROP TABLE IF EXISTS eval_datasets",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
