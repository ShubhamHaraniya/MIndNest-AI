"""Module labels and "last opened" for study materials.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# `module` lets a student group a course's files the way the syllabus does ("Unit 2", "Week 5").
# `last_opened_at` is stamped when a file is opened or a chat source is inspected, so the dashboard
# can show what the student was actually reading.
UPGRADE = [
    "ALTER TABLE materials ADD COLUMN module text CHECK (module IS NULL OR char_length(module) BETWEEN 1 AND 80)",
    "ALTER TABLE materials ADD COLUMN last_opened_at timestamptz",
    "CREATE INDEX materials_opened_idx ON materials (owner_id, last_opened_at DESC) WHERE last_opened_at IS NOT NULL",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS materials_opened_idx"))
    op.execute(sa.text("ALTER TABLE materials DROP COLUMN IF EXISTS last_opened_at"))
    op.execute(sa.text("ALTER TABLE materials DROP COLUMN IF EXISTS module"))
