"""Initial schema: accounts, subjects, materials, chunks, chat, agent runs, evaluation.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# One statement per entry: asyncpg cannot run several commands in one prepared statement.
UPGRADE = [
    # --- guard: the roles come from infra/compose/initdb/01-roles.sql ------------------
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_app')
         OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_eval') THEN
        RAISE EXCEPTION 'Roles mindnest_app and mindnest_eval are missing. Run infra/compose/initdb/01-roles.sql first.';
      END IF;
    END
    $$
    """,
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # --- row-level security context ------------------------------------------------------
    # The API sets app.user_id per transaction (see mindnest_core.db.user_session).
    # NULLIF guards against the empty string a pooled connection keeps after the setting ends.
    """
    CREATE FUNCTION app_current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$
    """,
    # --- accounts --------------------------------------------------------------------------
    """
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email text NOT NULL,
      password_hash text NOT NULL,
      display_name text NOT NULL,
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
      email_verified_at timestamptz,
      timezone text NOT NULL DEFAULT 'UTC',
      ui_language text NOT NULL DEFAULT 'en' CHECK (ui_language IN ('en', 'hi', 'gu')),
      answer_language text CHECK (answer_language IN ('en', 'hi', 'gu')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email))",
    # --- subjects and topics -----------------------------------------------------------------
    """
    CREATE TABLE subjects (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      owner_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      institution_id uuid,
      name text NOT NULL,
      course_code text,
      semester text,
      description text,
      archived_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX subjects_owner_idx ON subjects (owner_id)",
    """
    CREATE TABLE topics (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      subject_id uuid NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
      parent_id uuid REFERENCES topics (id) ON DELETE CASCADE,
      name text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX topics_subject_idx ON topics (subject_id)",
    # --- materials, ingestion and chunks -----------------------------------------------------
    """
    CREATE TABLE materials (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      subject_id uuid NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
      owner_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      institution_id uuid,
      kind text NOT NULL DEFAULT 'material'
        CHECK (kind IN ('material', 'past_paper', 'note', 'assignment')),
      filename text NOT NULL,
      mime_type text,
      size_bytes bigint,
      storage_key text NOT NULL,
      status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
      visibility text NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private', 'institution', 'global')),
      version integer NOT NULL DEFAULT 1,
      license text,
      language text CHECK (language IN ('en', 'hi', 'gu')),
      error text,
      deleted_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX materials_subject_idx ON materials (subject_id)",
    "CREATE INDEX materials_owner_idx ON materials (owner_id)",
    """
    CREATE TABLE ingestion_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      material_id uuid NOT NULL REFERENCES materials (id) ON DELETE CASCADE,
      stage text NOT NULL CHECK (stage IN ('validate', 'parse', 'ocr', 'chunk', 'embed')),
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
      attempts integer NOT NULL DEFAULT 0,
      error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ingestion_jobs_material_idx ON ingestion_jobs (material_id)",
    # Chunks copy owner, subject, institution and visibility so retrieval can filter in the
    # same SQL statement as the vector and keyword search. vector(1024) matches BGE-M3.
    """
    CREATE TABLE chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      material_id uuid NOT NULL REFERENCES materials (id) ON DELETE CASCADE,
      material_version integer NOT NULL DEFAULT 1,
      subject_id uuid NOT NULL,
      owner_id uuid NOT NULL,
      institution_id uuid,
      visibility text NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private', 'institution', 'global')),
      topic_id uuid REFERENCES topics (id) ON DELETE SET NULL,
      page integer,
      section text,
      text text NOT NULL,
      language text CHECK (language IN ('en', 'hi', 'gu')),
      embedding vector(1024),
      embedding_model text,
      tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
      is_active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX chunks_material_idx ON chunks (material_id)",
    "CREATE INDEX chunks_subject_idx ON chunks (subject_id)",
    "CREATE INDEX chunks_embedding_hnsw_idx ON chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv)",
    "CREATE INDEX chunks_text_trgm_idx ON chunks USING gin (text gin_trgm_ops)",
    # --- chat and agent runs -------------------------------------------------------------------
    """
    CREATE TABLE conversations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      subject_id uuid REFERENCES subjects (id) ON DELETE SET NULL,
      title text NOT NULL DEFAULT 'New chat',
      provider text,
      model text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX conversations_user_idx ON conversations (user_id)",
    """
    CREATE TABLE agent_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
      graph_version text NOT NULL,
      status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'interrupted', 'completed', 'failed', 'cancelled')),
      interrupt jsonb,
      langsmith_run_id text,
      prompt_tokens integer,
      completion_tokens integer,
      latency_ms integer,
      error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX agent_runs_user_idx ON agent_runs (user_id)",
    """
    CREATE TABLE messages (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
      role text NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
      blocks jsonb NOT NULL DEFAULT '[]'::jsonb,
      run_id uuid REFERENCES agent_runs (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at)",
    """
    CREATE TABLE agent_steps (
      id bigserial PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
      seq integer NOT NULL,
      node text NOT NULL,
      tool text,
      args_redacted jsonb,
      outcome text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (run_id, seq)
    )
    """,
    # --- grants for the app role ----------------------------------------------------------------
    "GRANT USAGE ON SCHEMA public TO mindnest_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mindnest_app",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mindnest_app",
    """
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mindnest_app
    """,
    """
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT USAGE, SELECT ON SEQUENCES TO mindnest_app
    """,
    # --- row-level security ----------------------------------------------------------------------
    # mindnest_app is not the table owner, so these policies always apply to it.
    # Sharing rules for institution and global material arrive in Stage 8.
    "ALTER TABLE subjects ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY subjects_owner ON subjects FOR ALL TO mindnest_app
      USING (owner_id = app_current_user_id())
      WITH CHECK (owner_id = app_current_user_id())
    """,
    "ALTER TABLE topics ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY topics_via_subject ON topics FOR ALL TO mindnest_app
      USING (EXISTS (SELECT 1 FROM subjects s WHERE s.id = topics.subject_id))
      WITH CHECK (EXISTS (SELECT 1 FROM subjects s WHERE s.id = topics.subject_id))
    """,
    "ALTER TABLE materials ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY materials_owner ON materials FOR ALL TO mindnest_app
      USING (owner_id = app_current_user_id())
      WITH CHECK (owner_id = app_current_user_id())
    """,
    "ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY ingestion_jobs_via_material ON ingestion_jobs FOR ALL TO mindnest_app
      USING (EXISTS (SELECT 1 FROM materials m WHERE m.id = ingestion_jobs.material_id))
      WITH CHECK (EXISTS (SELECT 1 FROM materials m WHERE m.id = ingestion_jobs.material_id))
    """,
    "ALTER TABLE chunks ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY chunks_owner ON chunks FOR ALL TO mindnest_app
      USING (owner_id = app_current_user_id())
      WITH CHECK (owner_id = app_current_user_id())
    """,
    "ALTER TABLE conversations ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY conversations_owner ON conversations FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id())
      WITH CHECK (user_id = app_current_user_id())
    """,
    "ALTER TABLE messages ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY messages_via_conversation ON messages FOR ALL TO mindnest_app
      USING (EXISTS (SELECT 1 FROM conversations c WHERE c.id = messages.conversation_id))
      WITH CHECK (EXISTS (SELECT 1 FROM conversations c WHERE c.id = messages.conversation_id))
    """,
    "ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY agent_runs_owner ON agent_runs FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id())
      WITH CHECK (user_id = app_current_user_id())
    """,
    "ALTER TABLE agent_steps ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY agent_steps_via_run ON agent_steps FOR ALL TO mindnest_app
      USING (EXISTS (SELECT 1 FROM agent_runs r WHERE r.id = agent_steps.run_id))
      WITH CHECK (EXISTS (SELECT 1 FROM agent_runs r WHERE r.id = agent_steps.run_id))
    """,
    # --- evaluation schema: separate from student data, reachable only by mindnest_eval ----------
    "CREATE SCHEMA eval",
    """
    CREATE TABLE eval.datasets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name text NOT NULL,
      version integer NOT NULL DEFAULT 1,
      kind text NOT NULL CHECK (kind IN ('rag', 'agent', 'quiz', 'diagram', 'security')),
      description text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (name, version)
    )
    """,
    """
    CREATE TABLE eval.cases (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_id uuid NOT NULL REFERENCES eval.datasets (id) ON DELETE CASCADE,
      language text CHECK (language IN ('en', 'hi', 'gu')),
      question text NOT NULL,
      expected jsonb NOT NULL DEFAULT '{}'::jsonb,
      tags text[] NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX eval_cases_dataset_idx ON eval.cases (dataset_id)",
    """
    CREATE TABLE eval.runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_id uuid NOT NULL REFERENCES eval.datasets (id),
      config jsonb NOT NULL,
      git_sha text,
      graph_version text,
      prompt_version text,
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
      started_at timestamptz,
      finished_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE eval.results (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      run_id uuid NOT NULL REFERENCES eval.runs (id) ON DELETE CASCADE,
      case_id uuid NOT NULL REFERENCES eval.cases (id),
      scores jsonb NOT NULL DEFAULT '{}'::jsonb,
      failure_category text,
      trace_url text,
      latency_ms integer,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (run_id, case_id)
    )
    """,
    "GRANT USAGE ON SCHEMA eval TO mindnest_eval",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA eval TO mindnest_eval",
    """
    ALTER DEFAULT PRIVILEGES IN SCHEMA eval
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mindnest_eval
    """,
]

DOWNGRADE = [
    "DROP SCHEMA IF EXISTS eval CASCADE",
    "DROP TABLE IF EXISTS agent_steps",
    "DROP TABLE IF EXISTS messages",
    "DROP TABLE IF EXISTS agent_runs",
    "DROP TABLE IF EXISTS conversations",
    "DROP TABLE IF EXISTS chunks",
    "DROP TABLE IF EXISTS ingestion_jobs",
    "DROP TABLE IF EXISTS materials",
    "DROP TABLE IF EXISTS topics",
    "DROP TABLE IF EXISTS subjects",
    "DROP TABLE IF EXISTS users",
    "DROP FUNCTION IF EXISTS app_current_user_id()",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
