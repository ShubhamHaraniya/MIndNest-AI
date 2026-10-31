"""Quizzes can be archived (hidden from the active list, kept with their results).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

UPGRADE: list[str] = [
    "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS archived_at timestamptz",
    "CREATE INDEX IF NOT EXISTS quizzes_archived_idx ON quizzes (user_id, archived_at)",
]
DOWNGRADE: list[str] = [
    "DROP INDEX IF EXISTS quizzes_archived_idx",
    "ALTER TABLE quizzes DROP COLUMN IF EXISTS archived_at",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
