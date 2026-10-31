"""Assignment workspace: files, rubric and revision history (filled in with the assignments redesign).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# The workspace around an assignment: a marking rubric, files attached to it (rows of `materials`,
# so they are stored, scanned and searchable like any other upload) and snapshots of the draft.
# Every statement can be run twice, so a development database that already recorded this revision
# can be brought up to date by executing UPGRADE directly.
UPGRADE: list[str] = [
    "ALTER TABLE assignments ADD COLUMN IF NOT EXISTS rubric jsonb",
    """
    CREATE TABLE IF NOT EXISTS assignment_files (
      assignment_id uuid NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
      material_id uuid NOT NULL REFERENCES materials (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (assignment_id, material_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS assignment_files_material_idx ON assignment_files (material_id)",
    """
    CREATE TABLE IF NOT EXISTS assignment_revisions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      assignment_id uuid NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      body text NOT NULL,
      word_count integer NOT NULL DEFAULT 0,
      source text NOT NULL DEFAULT 'auto'
        CHECK (source IN ('auto', 'manual', 'restore', 'feedback', 'baseline')),
      note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 200),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS assignment_revisions_idx ON assignment_revisions (assignment_id, updated_at DESC)",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON assignment_files, assignment_revisions TO mindnest_app",
]

for _table in ("assignment_files", "assignment_revisions"):
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(f"DROP POLICY IF EXISTS {_table}_owner ON {_table}")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

# Statements applied by downgrade(), in order (reverse of UPGRADE).
DOWNGRADE: list[str] = [
    "DROP TABLE IF EXISTS assignment_revisions",
    "DROP TABLE IF EXISTS assignment_files",
    "ALTER TABLE assignments DROP COLUMN IF EXISTS rubric",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
