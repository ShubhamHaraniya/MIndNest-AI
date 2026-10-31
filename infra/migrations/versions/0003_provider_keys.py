"""Per-user AI provider keys (bring your own key).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# The key itself is stored encrypted (Fernet); key_hint keeps only the last four characters so
# Settings can show which key is saved without ever sending it back to the browser.
UPGRADE = [
    """
    CREATE TABLE provider_keys (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      provider text NOT NULL CHECK (provider IN ('anthropic', 'gemini', 'openai', 'groq')),
      ciphertext text NOT NULL,
      key_hint text NOT NULL,
      model text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (user_id, provider)
    )
    """,
    "ALTER TABLE provider_keys ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY provider_keys_owner ON provider_keys FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id())
      WITH CHECK (user_id = app_current_user_id())
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON provider_keys TO mindnest_app",
    "CREATE INDEX conversations_user_updated_idx ON conversations (user_id, updated_at DESC)",
]

DOWNGRADE = [
    "DROP INDEX IF EXISTS conversations_user_updated_idx",
    "DROP TABLE IF EXISTS provider_keys",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
