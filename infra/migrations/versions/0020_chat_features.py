"""Chat: what a conversation may search, attached files, answer feedback, and regenerated answers.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

UPGRADE: list[str] = [
    # --- what a conversation may search: every course, one course, or chosen files ---------------
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'all'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS material_ids uuid[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_scope_check",
    "ALTER TABLE conversations ADD CONSTRAINT conversations_scope_check "
    "CHECK (scope IN ('all', 'subject', 'materials'))",
    # A chat started inside a course has always searched that course; keep saying so.
    "UPDATE conversations SET scope = 'subject' WHERE subject_id IS NOT NULL AND scope = 'all'",
    # --- regenerated answers: the old answer is kept, hidden, and linked from the new one --------
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS replaces_id uuid REFERENCES messages (id) ON DELETE SET NULL",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS superseded_at timestamptz",
    "CREATE INDEX IF NOT EXISTS messages_replaces_idx ON messages (replaces_id) WHERE replaces_id IS NOT NULL",
    # --- files attached to a conversation (their text is read by the worker) ---------------------
    """
    CREATE TABLE IF NOT EXISTS chat_attachments (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
      filename text NOT NULL CHECK (char_length(filename) BETWEEN 1 AND 255),
      extension text NOT NULL,
      kind text NOT NULL CHECK (kind IN ('pdf', 'docx', 'image')),
      size_bytes bigint NOT NULL CHECK (size_bytes > 0),
      storage_key text NOT NULL,
      status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
      error text,
      text_content text NOT NULL DEFAULT '',
      char_count integer NOT NULL DEFAULT 0,
      page_count integer,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS chat_attachments_conv_idx ON chat_attachments (conversation_id, created_at)",
    # --- thumbs up / down on an answer, one per student per answer -------------------------------
    """
    CREATE TABLE IF NOT EXISTS message_feedback (
      message_id uuid NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      rating text NOT NULL CHECK (rating IN ('up', 'down')),
      reason text CHECK (reason IN ('incorrect', 'not_in_materials', 'unclear', 'too_long', 'unsafe', 'other')),
      comment text NOT NULL DEFAULT '' CHECK (char_length(comment) <= 500),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (message_id, user_id)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON chat_attachments, message_feedback TO mindnest_app",
]

for _table in ("chat_attachments", "message_feedback"):
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")
    UPGRADE.append(f"DROP POLICY IF EXISTS {_table}_owner ON {_table}")
    UPGRADE.append(
        f"""
        CREATE POLICY {_table}_owner ON {_table} FOR ALL TO mindnest_app
          USING (user_id = app_current_user_id())
          WITH CHECK (user_id = app_current_user_id())
        """
    )

DOWNGRADE: list[str] = [
    "DROP TABLE IF EXISTS message_feedback",
    "DROP TABLE IF EXISTS chat_attachments",
    "DROP INDEX IF EXISTS messages_replaces_idx",
    "ALTER TABLE messages DROP COLUMN IF EXISTS superseded_at",
    "ALTER TABLE messages DROP COLUMN IF EXISTS replaces_id",
    "ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_scope_check",
    "ALTER TABLE conversations DROP COLUMN IF EXISTS material_ids",
    "ALTER TABLE conversations DROP COLUMN IF EXISTS scope",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
