"""Which notifications a student has already seen.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# Notifications are worked out from the student's own data every time they are asked for (an exam
# in three days, an assignment past its due date, flashcards waiting ...), so nothing is stored for
# them. This table only remembers which ones were read. A key names the thing and how urgent it
# was ("exam:<id>:d3"), so when an exam gets closer the student is told again.
UPGRADE = [
    """
    CREATE TABLE notification_reads (
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      key text NOT NULL CHECK (char_length(key) BETWEEN 1 AND 200),
      read_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, key)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON notification_reads TO mindnest_app",
    "ALTER TABLE notification_reads ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY notification_reads_owner ON notification_reads FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id())
      WITH CHECK (user_id = app_current_user_id())
    """,
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS notification_reads"))
