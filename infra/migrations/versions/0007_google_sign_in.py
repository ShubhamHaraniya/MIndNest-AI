"""Sign in with Google: linked identities, and accounts that have no password.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# user_identities has no row-level security on purpose, like sessions: it is read by the
# provider's account id before anyone is known to be signed in. It stores no secrets, only
# Google's stable account id ("sub") and the email Google reported when the link was made.
UPGRADE = [
    # A student who signs up with Google never chooses a password.
    "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL",
    """
    CREATE TABLE user_identities (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      provider text NOT NULL CHECK (provider IN ('google')),
      subject text NOT NULL,
      email text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      last_login_at timestamptz,
      UNIQUE (provider, subject),
      UNIQUE (user_id, provider)
    )
    """,
    "CREATE INDEX user_identities_user_idx ON user_identities (user_id)",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON user_identities TO mindnest_app",
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS user_identities",
    # Accounts without a password cannot be given one here; they keep an unusable hash.
    "UPDATE users SET password_hash = '!' WHERE password_hash IS NULL",
    "ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
