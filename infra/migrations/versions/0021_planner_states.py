"""Study planner: a task can be cancelled, and a planner task the student moved stays put.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# 'skipped' was the old name for a task dropped on purpose; it becomes 'cancelled'. The web app
# and the API still accept "skipped" and store it as 'cancelled'. A plan task the student moved or
# resized is `pinned`: generating the plan again keeps it, like a task the student wrote.
UPGRADE: list[str] = [
    "ALTER TABLE study_tasks DROP CONSTRAINT IF EXISTS study_tasks_status_check",
    "UPDATE study_tasks SET status = 'cancelled' WHERE status = 'skipped'",
    """
    ALTER TABLE study_tasks ADD CONSTRAINT study_tasks_status_check
      CHECK (status IN ('todo', 'done', 'cancelled', 'skipped'))
    """,
    "ALTER TABLE study_tasks ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false",
]

DOWNGRADE: list[str] = [
    "ALTER TABLE study_tasks DROP COLUMN IF EXISTS pinned",
    "ALTER TABLE study_tasks DROP CONSTRAINT IF EXISTS study_tasks_status_check",
    "UPDATE study_tasks SET status = 'skipped' WHERE status = 'cancelled'",
    """
    ALTER TABLE study_tasks ADD CONSTRAINT study_tasks_status_check
      CHECK (status IN ('todo', 'done', 'skipped'))
    """,
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
