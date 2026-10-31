"""Agent layer: LangGraph checkpoints (with row-level security) and richer run records.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# The checkpoint tables below are exactly what langgraph-checkpoint-postgres creates for itself
# (AsyncPostgresSaver.setup()), minus CONCURRENTLY on the indexes, which cannot run inside a
# migration transaction. Creating them here lets the application role stay without CREATE rights
# and lets us put row-level security on them. The checkpoint_migrations rows mark the library's
# own steps as done, so setup() would find nothing to do. A test compares this number to the
# installed library, so an upgrade that adds a step is noticed.
LIBRARY_MIGRATION_COUNT = 10

# Thread ids are "<user id>:<conversation id>" (mindnest_agents.checkpoint.thread_id). The policy
# reads the part before the colon, so a student's connection only ever sees their own threads.
OWN_THREAD = "split_part(thread_id, ':', 1) = app_current_user_id()::text"

UPGRADE = [
    # --- LangGraph checkpoints -------------------------------------------------------------------
    "CREATE TABLE checkpoint_migrations (v integer PRIMARY KEY)",
    """
    CREATE TABLE checkpoints (
      thread_id text NOT NULL,
      checkpoint_ns text NOT NULL DEFAULT '',
      checkpoint_id text NOT NULL,
      parent_checkpoint_id text,
      type text,
      checkpoint jsonb NOT NULL,
      metadata jsonb NOT NULL DEFAULT '{}',
      PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )
    """,
    """
    CREATE TABLE checkpoint_blobs (
      thread_id text NOT NULL,
      checkpoint_ns text NOT NULL DEFAULT '',
      channel text NOT NULL,
      version text NOT NULL,
      type text NOT NULL,
      blob bytea,
      PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    )
    """,
    """
    CREATE TABLE checkpoint_writes (
      thread_id text NOT NULL,
      checkpoint_ns text NOT NULL DEFAULT '',
      checkpoint_id text NOT NULL,
      task_id text NOT NULL,
      idx integer NOT NULL,
      channel text NOT NULL,
      type text,
      blob bytea NOT NULL,
      task_path text NOT NULL DEFAULT '',
      PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )
    """,
    "CREATE INDEX checkpoints_thread_id_idx ON checkpoints (thread_id)",
    "CREATE INDEX checkpoint_blobs_thread_id_idx ON checkpoint_blobs (thread_id)",
    "CREATE INDEX checkpoint_writes_thread_id_idx ON checkpoint_writes (thread_id)",
    f"INSERT INTO checkpoint_migrations (v) SELECT g FROM generate_series(0, {LIBRARY_MIGRATION_COUNT - 1}) g",
    "GRANT SELECT ON checkpoint_migrations TO mindnest_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, checkpoint_writes TO mindnest_app",
    *[
        stmt
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
        for stmt in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"""
            CREATE POLICY {table}_own_thread ON {table} FOR ALL TO mindnest_app
              USING ({OWN_THREAD}) WITH CHECK ({OWN_THREAD})
            """,
        )
    ],
    # Deleting a conversation (or an account, which cascades) deletes its saved agent state too.
    """
    CREATE FUNCTION conversations_delete_checkpoints() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    BEGIN
      DELETE FROM checkpoint_writes WHERE thread_id = OLD.user_id::text || ':' || OLD.id::text;
      DELETE FROM checkpoint_blobs  WHERE thread_id = OLD.user_id::text || ':' || OLD.id::text;
      DELETE FROM checkpoints       WHERE thread_id = OLD.user_id::text || ':' || OLD.id::text;
      RETURN OLD;
    END
    $$
    """,
    """
    CREATE TRIGGER conversations_delete_checkpoints AFTER DELETE ON conversations
      FOR EACH ROW EXECUTE FUNCTION conversations_delete_checkpoints()
    """,
    # --- richer run records -----------------------------------------------------------------------
    "ALTER TABLE agent_runs ADD COLUMN thread_id text",
    # What the orchestrator decided: which agent(s) it chose and why (redacted).
    "ALTER TABLE agent_runs ADD COLUMN route jsonb",
    "CREATE INDEX agent_runs_conversation_idx ON agent_runs (conversation_id, created_at)",
    "ALTER TABLE agent_steps ADD COLUMN agent text",
    "ALTER TABLE agent_steps ADD COLUMN duration_ms integer",
]

DOWNGRADE = [
    "ALTER TABLE agent_steps DROP COLUMN duration_ms",
    "ALTER TABLE agent_steps DROP COLUMN agent",
    "DROP INDEX agent_runs_conversation_idx",
    "ALTER TABLE agent_runs DROP COLUMN route",
    "ALTER TABLE agent_runs DROP COLUMN thread_id",
    "DROP TRIGGER conversations_delete_checkpoints ON conversations",
    "DROP FUNCTION conversations_delete_checkpoints()",
    "DROP TABLE checkpoint_writes",
    "DROP TABLE checkpoint_blobs",
    "DROP TABLE checkpoints",
    "DROP TABLE checkpoint_migrations",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
