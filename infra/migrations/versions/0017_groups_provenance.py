"""Library provenance and publication status (filled in with the study groups redesign).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

# Statements applied by upgrade(), in order.
UPGRADE: list[str] = [
    # Where a shared file came from. The course is the sharer's course at the time, kept as text
    # because the shared file is a copy that outlives it; author and institution are what the sharer
    # says about the original; rights says why they may pass it on.
    "ALTER TABLE shared_items ADD COLUMN IF NOT EXISTS course_name text",
    "ALTER TABLE shared_items ADD COLUMN IF NOT EXISTS author text NOT NULL DEFAULT ''",
    "ALTER TABLE shared_items ADD COLUMN IF NOT EXISTS institution text NOT NULL DEFAULT ''",
    "ALTER TABLE shared_items ADD COLUMN IF NOT EXISTS rights text NOT NULL DEFAULT 'own_work'",
    "ALTER TABLE shared_items DROP CONSTRAINT IF EXISTS shared_items_rights_check",
    "ALTER TABLE shared_items ADD CONSTRAINT shared_items_rights_check "
    "CHECK (rights IN ('own_work', 'permitted', 'open_licence'))",
]
# Statements applied by downgrade(), in order (reverse of UPGRADE).
DOWNGRADE: list[str] = [
    "ALTER TABLE shared_items DROP CONSTRAINT IF EXISTS shared_items_rights_check",
    "ALTER TABLE shared_items DROP COLUMN IF EXISTS rights",
    "ALTER TABLE shared_items DROP COLUMN IF EXISTS institution",
    "ALTER TABLE shared_items DROP COLUMN IF EXISTS author",
    "ALTER TABLE shared_items DROP COLUMN IF EXISTS course_name",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
