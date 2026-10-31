"""Personal-data privacy setting and a log of safety events.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# security_events holds COUNTS and kinds only ("2 e-mail addresses masked", "instruction-like
# text found in notes.pdf"), never the text itself, so the log cannot leak what it protects.
UPGRADE = [
    "ALTER TABLE users ADD COLUMN mask_personal_data boolean NOT NULL DEFAULT true",
    """
    CREATE TABLE security_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      kind text NOT NULL,
      source text NOT NULL,
      detail jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX security_events_user_idx ON security_events (user_id, created_at DESC)",
    "CREATE INDEX security_events_kind_idx ON security_events (kind, created_at DESC)",
    "GRANT SELECT, INSERT, DELETE ON security_events TO mindnest_app",
    "ALTER TABLE security_events ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY security_events_owner ON security_events FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id())
      WITH CHECK (user_id = app_current_user_id())
    """,
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS security_events",
    "ALTER TABLE users DROP COLUMN IF EXISTS mask_personal_data",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
