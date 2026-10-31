"""Sessions, email tokens and onboarding progress.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# sessions and email_tokens have no row-level security on purpose: they are looked up by the
# hash of a secret token before anyone is known to be signed in. Only the hash is stored, so a
# leaked database dump cannot be replayed as a login.
UPGRADE = [
    """
    ALTER TABLE users
      ADD COLUMN onboarding_step integer NOT NULL DEFAULT 0 CHECK (onboarding_step BETWEEN 0 AND 5),
      ADD COLUMN onboarding_completed_at timestamptz
    """,
    """
    CREATE TABLE sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      token_hash text NOT NULL UNIQUE,
      expires_at timestamptz NOT NULL,
      user_agent text,
      created_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX sessions_user_idx ON sessions (user_id)",
    "CREATE INDEX sessions_expires_idx ON sessions (expires_at)",
    """
    CREATE TABLE email_tokens (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      kind text NOT NULL CHECK (kind IN ('verify_email', 'reset_password')),
      token_hash text NOT NULL UNIQUE,
      expires_at timestamptz NOT NULL,
      used_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX email_tokens_user_idx ON email_tokens (user_id, kind)",
    # Tables created by this migration inherit the app-role grants through the default
    # privileges set in 0001; these statements make that explicit and safe to re-run.
    "GRANT SELECT, INSERT, UPDATE, DELETE ON sessions, email_tokens TO mindnest_app",
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS email_tokens",
    "DROP TABLE IF EXISTS sessions",
    "ALTER TABLE users DROP COLUMN IF EXISTS onboarding_completed_at",
    "ALTER TABLE users DROP COLUMN IF EXISTS onboarding_step",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
