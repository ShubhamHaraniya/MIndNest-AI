"""Google Calendar connection and the record of what was sent (per student).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# The refresh token is stored encrypted (Fernet, key derived from SECRET_KEY), exactly like the
# AI provider keys. calendar_sync_items remembers which Google event belongs to which exam,
# assignment or study task, and a fingerprint of what was sent, so only real changes are
# proposed next time. It has no foreign key to the source because the source can be any of three
# tables; the API removes entries when it deletes the event.
UPGRADE = [
    """
    CREATE TABLE google_calendar_links (
      user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
      refresh_token_enc text NOT NULL,
      scope text NOT NULL DEFAULT '',
      calendar_id text,
      needs_reconnect boolean NOT NULL DEFAULT false,
      connected_at timestamptz NOT NULL DEFAULT now(),
      last_synced_at timestamptz
    )
    """,
    """
    CREATE TABLE calendar_sync_items (
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      source_type text NOT NULL CHECK (source_type IN ('exam', 'assignment', 'task')),
      source_id uuid NOT NULL,
      day date NOT NULL,
      fingerprint text NOT NULL,
      google_event_id text NOT NULL,
      synced_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, source_type, source_id)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON google_calendar_links, calendar_sync_items TO mindnest_app",
]

_TABLES = ("google_calendar_links", "calendar_sync_items")
for _table in _TABLES:
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

DOWNGRADE = [f"DROP TABLE IF EXISTS {t}" for t in reversed(_TABLES)]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
