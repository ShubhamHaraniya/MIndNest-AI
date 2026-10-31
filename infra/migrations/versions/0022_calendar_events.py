"""Calendar: events the student adds, and what went wrong when sending items to Google.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# calendar_events: a student's own event (a lecture, a lab, an appointment). `request_key` lets the
# browser send the same "add event" twice (a double click, a retry after a dropped connection) and
# get one event back. The last unique index refuses two events with the same title at the same
# time on the same day.
#
# calendar_sync_failures: one row per item that Google refused or could not be reached for, with
# how often it was tried. The row is removed when a later send works, so the Calendar page can say
# "waiting", "failed" or "synced" for every item and offer Retry.
UPGRADE: list[str] = [
    """
    CREATE TABLE calendar_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      title text NOT NULL,
      notes text NOT NULL DEFAULT '',
      day date NOT NULL,
      start_time text NOT NULL DEFAULT ''
        CHECK (start_time = '' OR start_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
      minutes integer NOT NULL DEFAULT 60 CHECK (minutes BETWEEN 5 AND 1440),
      sync_to_google boolean NOT NULL DEFAULT false,
      request_key text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX calendar_events_user_day_idx ON calendar_events (user_id, day)",
    "CREATE UNIQUE INDEX calendar_events_request_key_uq ON calendar_events (user_id, request_key) "
    "WHERE request_key IS NOT NULL",
    "CREATE UNIQUE INDEX calendar_events_twin_uq ON calendar_events (user_id, lower(title), day, start_time)",
    """
    CREATE TABLE calendar_sync_failures (
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      source_type text NOT NULL CHECK (source_type IN ('exam', 'assignment', 'task', 'event')),
      source_id uuid NOT NULL,
      action text NOT NULL CHECK (action IN ('create', 'update', 'delete')),
      error text NOT NULL,
      attempts integer NOT NULL DEFAULT 1,
      first_failed_at timestamptz NOT NULL DEFAULT now(),
      last_failed_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, source_type, source_id)
    )
    """,
    "ALTER TABLE calendar_sync_items DROP CONSTRAINT IF EXISTS calendar_sync_items_source_type_check",
    """
    ALTER TABLE calendar_sync_items ADD CONSTRAINT calendar_sync_items_source_type_check
      CHECK (source_type IN ('exam', 'assignment', 'task', 'event'))
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON calendar_events, calendar_sync_failures TO mindnest_app",
]

_TABLES = ("calendar_events", "calendar_sync_failures")
for _table in _TABLES:
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

DOWNGRADE: list[str] = [
    "DELETE FROM calendar_sync_items WHERE source_type = 'event'",
    "ALTER TABLE calendar_sync_items DROP CONSTRAINT IF EXISTS calendar_sync_items_source_type_check",
    """
    ALTER TABLE calendar_sync_items ADD CONSTRAINT calendar_sync_items_source_type_check
      CHECK (source_type IN ('exam', 'assignment', 'task'))
    """,
    *[f"DROP TABLE IF EXISTS {t}" for t in reversed(_TABLES)],
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
