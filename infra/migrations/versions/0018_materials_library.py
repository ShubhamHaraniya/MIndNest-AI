"""Institution on the profile, and the Materials Library (college, other colleges, global).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# What a student publishes to the library is a COPY of the file in object storage, so the original
# can change or go away, and a takedown removes exactly what was published.
#
# Who can read a row (row-level security):
#   * the owner, always;
#   * anyone, when the item is published and public;
#   * a student whose institution matches, when it is published and institution-only.
# Private uploads never get a library row that anyone else can see, and they are never part of the
# retrieval index of anybody but their owner. Copies that other students add to their own courses
# are ordinary private materials (materials.library_item_id remembers where they came from), so a
# takedown can remove them from the index too.
#
# Moderators work through SECURITY DEFINER functions that check app_is_admin() first, as the rest
# of the admin screens do. They never read file contents.
UPGRADE: list[str] = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS institution_name text NOT NULL DEFAULT ''",
    # One spelling of an institution for comparing: case-insensitive, spaces collapsed.
    """
    CREATE FUNCTION app_inst_key(p_name text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT lower(btrim(regexp_replace(COALESCE(p_name, ''), '\\s+', ' ', 'g'))) $$
    """,
    """
    CREATE FUNCTION app_my_institution_key() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$ SELECT app_inst_key(institution_name) FROM users WHERE id = app_current_user_id() $$
    """,
    """
    CREATE TABLE library_items (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      owner_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      source_material_id uuid REFERENCES materials (id) ON DELETE SET NULL,
      title text NOT NULL,
      description text NOT NULL DEFAULT '',
      doc_type text NOT NULL DEFAULT 'notes'
        CHECK (doc_type IN ('notes', 'past_paper', 'textbook', 'slides', 'reference', 'other')),
      course_name text NOT NULL DEFAULT '',
      topic text NOT NULL DEFAULT '',
      semester text NOT NULL DEFAULT '',
      academic_year text NOT NULL DEFAULT '',
      author text NOT NULL DEFAULT '',
      institution text NOT NULL DEFAULT '',
      institution_key text NOT NULL DEFAULT '',
      rights text NOT NULL DEFAULT 'own_work' CHECK (rights IN ('own_work', 'permitted', 'open_licence')),
      visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'institution', 'public')),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'pending_review', 'published', 'rejected', 'held', 'taken_down')),
      review_note text NOT NULL DEFAULT '',
      reviewed_by uuid REFERENCES users (id) ON DELETE SET NULL,
      reviewed_at timestamptz,
      taken_down_at timestamptz,
      filename text NOT NULL,
      mime_type text,
      size_bytes bigint,
      storage_key text NOT NULL,
      published_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX library_items_owner_idx ON library_items (owner_id, created_at DESC)",
    "CREATE INDEX library_items_browse_idx ON library_items (status, visibility, institution_key)",
    "CREATE UNIQUE INDEX library_items_source_idx ON library_items (owner_id, source_material_id) "
    "WHERE source_material_id IS NOT NULL",
    """
    CREATE TABLE library_reports (
      item_id uuid NOT NULL REFERENCES library_items (id) ON DELETE CASCADE,
      reporter_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      reason text NOT NULL CHECK (reason IN ('copyright', 'inappropriate', 'wrong_content', 'other')),
      note text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (item_id, reporter_id)
    )
    """,
    # Where a student's course material came from, so a takedown can reach the copies.
    "ALTER TABLE materials ADD COLUMN IF NOT EXISTS library_item_id uuid REFERENCES library_items (id) "
    "ON DELETE SET NULL",
    "CREATE INDEX materials_library_item_idx ON materials (library_item_id) WHERE library_item_id IS NOT NULL",
    # --- reading rules -------------------------------------------------------------------------
    """
    CREATE FUNCTION app_library_can_read(p_owner uuid, p_status text, p_visibility text, p_key text)
    RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT p_owner = app_current_user_id()
        OR (p_status = 'published' AND p_visibility = 'public')
        OR (p_status = 'published' AND p_visibility = 'institution' AND p_key <> ''
            AND p_key = app_my_institution_key())
    $$
    """,
    # A student reports a published item that is not theirs. Several different reporters hold it
    # back until a moderator decides. Returns nothing when the item cannot be seen or is theirs.
    """
    CREATE FUNCTION app_library_report(p_item uuid, p_reason text, p_note text, p_hold_at integer)
    RETURNS TABLE (reports integer, held boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      me uuid := app_current_user_id();
      o uuid; s text; v text; k text; total integer; now_held boolean;
    BEGIN
      IF me IS NULL THEN RAISE EXCEPTION 'not signed in'; END IF;
      SELECT owner_id, status, visibility, institution_key INTO o, s, v, k FROM library_items WHERE id = p_item;
      IF o IS NULL OR o = me OR NOT app_library_can_read(o, s, v, k) THEN RETURN; END IF;
      INSERT INTO library_reports (item_id, reporter_id, reason, note) VALUES (p_item, me, p_reason, p_note)
        ON CONFLICT (item_id, reporter_id) DO UPDATE SET reason = p_reason, note = p_note;
      SELECT count(*) INTO total FROM library_reports WHERE item_id = p_item;
      IF total >= p_hold_at AND s = 'published' THEN
        UPDATE library_items SET status = 'held', updated_at = now() WHERE id = p_item;
      END IF;
      SELECT (status = 'held') INTO now_held FROM library_items WHERE id = p_item;
      RETURN QUERY SELECT total, now_held;
    END
    $$
    """,
    # Institution names other students have typed, for the suggestions in Settings. A name is only
    # offered once at least two students use it, so a name typed by one person is not exposed.
    """
    CREATE FUNCTION app_institution_names(p_query text, p_limit integer)
    RETURNS TABLE (name text, students integer)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT min(institution_name) AS name, count(*)::integer AS students
      FROM users
      WHERE institution_name <> '' AND status = 'active'
        AND (COALESCE(p_query, '') = '' OR app_inst_key(institution_name) LIKE '%' || app_inst_key(p_query) || '%')
      GROUP BY app_inst_key(institution_name)
      HAVING count(*) >= 2
      ORDER BY count(*) DESC, 1
      LIMIT LEAST(GREATEST(p_limit, 1), 30)
    $$
    """,
    # --- moderation (administrators only) -------------------------------------------------------
    """
    CREATE FUNCTION app_admin_library_queue()
    RETURNS TABLE (
      id uuid, title text, filename text, doc_type text, visibility text, status text, rights text,
      institution text, author text, owner_name text, reports integer,
      reasons jsonb, notes jsonb, imports integer, created_at timestamptz
    )
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    BEGIN
      IF NOT app_is_admin() THEN RAISE EXCEPTION 'admin only' USING ERRCODE = '42501'; END IF;
      RETURN QUERY
      SELECT i.id, i.title, i.filename, i.doc_type, i.visibility, i.status, i.rights, i.institution,
             i.author, u.display_name,
             (SELECT count(*)::integer FROM library_reports r WHERE r.item_id = i.id),
             COALESCE((SELECT jsonb_agg(DISTINCT r.reason) FROM library_reports r WHERE r.item_id = i.id), '[]'::jsonb),
             COALESCE((SELECT jsonb_agg(left(r.note, 300)) FROM library_reports r
                       WHERE r.item_id = i.id AND r.note <> ''), '[]'::jsonb),
             (SELECT count(*)::integer FROM materials m WHERE m.library_item_id = i.id AND m.deleted_at IS NULL),
             i.created_at
      FROM library_items i JOIN users u ON u.id = i.owner_id
      WHERE i.status IN ('pending_review', 'held')
         OR EXISTS (SELECT 1 FROM library_reports r WHERE r.item_id = i.id)
      ORDER BY (i.status = 'held') DESC, (i.status = 'pending_review') DESC, i.created_at;
    END
    $$
    """,
    # approve | reject | takedown. Returns the storage keys that must now be deleted (empty unless it
    # was a takedown) or NULL when the item does not exist. A takedown also pulls every copy that
    # students added to their courses out of the retrieval index (chunks) and hides those materials.
    """
    CREATE FUNCTION app_admin_library_decide(p_item uuid, p_action text, p_note text)
    RETURNS text[]
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      o uuid; fname text; k text; keys text[] := ARRAY[]::text[]; copies uuid[];
    BEGIN
      IF NOT app_is_admin() THEN RAISE EXCEPTION 'admin only' USING ERRCODE = '42501'; END IF;
      IF p_action NOT IN ('approve', 'reject', 'takedown') THEN RAISE EXCEPTION 'bad action'; END IF;
      SELECT owner_id, filename, storage_key INTO o, fname, k FROM library_items WHERE id = p_item;
      IF o IS NULL THEN RETURN NULL; END IF;
      IF p_action = 'approve' THEN
        UPDATE library_items SET status = 'published', review_note = '', reviewed_by = app_current_user_id(),
          reviewed_at = now(), published_at = COALESCE(published_at, now()), updated_at = now()
          WHERE id = p_item AND status IN ('pending_review', 'held', 'rejected');
        DELETE FROM library_reports WHERE item_id = p_item;
      ELSIF p_action = 'reject' THEN
        UPDATE library_items SET status = 'rejected', review_note = left(COALESCE(p_note, ''), 300),
          reviewed_by = app_current_user_id(), reviewed_at = now(), updated_at = now()
          WHERE id = p_item AND status IN ('pending_review', 'held', 'published');
      ELSE
        SELECT COALESCE(array_agg(id), ARRAY[]::uuid[]) INTO copies
          FROM materials WHERE library_item_id = p_item AND deleted_at IS NULL;
        DELETE FROM chunks WHERE material_id = ANY(copies);
        SELECT COALESCE(array_agg(storage_key), ARRAY[]::text[]) INTO keys
          FROM materials WHERE id = ANY(copies);
        UPDATE materials SET deleted_at = now(), status = 'failed', error = 'taken_down', updated_at = now()
          WHERE id = ANY(copies);
        UPDATE library_items SET status = 'taken_down', review_note = left(COALESCE(p_note, ''), 300),
          reviewed_by = app_current_user_id(), reviewed_at = now(), taken_down_at = now(),
          storage_key = '', updated_at = now()
          WHERE id = p_item;
        IF k <> '' THEN keys := keys || k; END IF;
      END IF;
      INSERT INTO admin_audit_log (admin_id, action, target_user, detail)
        VALUES (app_current_user_id(), 'library_' || p_action, o,
                jsonb_build_object('filename', left(fname, 200), 'note', left(COALESCE(p_note, ''), 300)));
      RETURN keys;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION app_library_can_read(uuid, text, text, text), app_my_institution_key(), "
    "app_library_report(uuid, text, text, integer), app_institution_names(text, integer), "
    "app_admin_library_queue(), app_admin_library_decide(uuid, text, text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_inst_key(text), app_library_can_read(uuid, text, text, text), "
    "app_my_institution_key(), app_library_report(uuid, text, text, integer), "
    "app_institution_names(text, integer), app_admin_library_queue(), "
    "app_admin_library_decide(uuid, text, text) TO mindnest_app",
    # --- table access --------------------------------------------------------------------------
    # The owner may change what describes the item and whether it is shared, but never the review
    # fields or the stored file; those are written by the moderation functions only.
    "GRANT SELECT, DELETE ON library_items TO mindnest_app",
    "GRANT INSERT (id, owner_id, source_material_id, title, description, doc_type, course_name, topic, "
    "semester, academic_year, author, institution, institution_key, rights, visibility, status, filename, "
    "mime_type, size_bytes, storage_key, published_at) ON library_items TO mindnest_app",
    "GRANT UPDATE (title, description, doc_type, course_name, topic, semester, academic_year, author, "
    "institution, institution_key, rights, visibility, status, published_at, updated_at) "
    "ON library_items TO mindnest_app",
    "GRANT SELECT ON library_reports TO mindnest_app",
    "ALTER TABLE library_items ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE library_reports ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY library_items_read ON library_items FOR SELECT TO mindnest_app
      USING (app_library_can_read(owner_id, status, visibility, institution_key))
    """,
    """
    CREATE POLICY library_items_add ON library_items FOR INSERT TO mindnest_app
      WITH CHECK (
        owner_id = app_current_user_id()
        AND (status = 'draft' OR status = 'pending_review' OR (status = 'published' AND visibility = 'institution'))
      )
    """,
    # Held, taken-down and rejected items are out of the owner's hands until a moderator acts;
    # the owner can still delete them. A public item can only be moved to review, never straight
    # to published.
    """
    CREATE POLICY library_items_update ON library_items FOR UPDATE TO mindnest_app
      USING (owner_id = app_current_user_id() AND status NOT IN ('held', 'taken_down'))
      WITH CHECK (
        owner_id = app_current_user_id()
        AND (status IN ('draft', 'pending_review') OR (status = 'published' AND visibility = 'institution'))
      )
    """,
    """
    CREATE POLICY library_items_delete ON library_items FOR DELETE TO mindnest_app
      USING (owner_id = app_current_user_id())
    """,
    """
    CREATE POLICY library_reports_own ON library_reports FOR SELECT TO mindnest_app
      USING (reporter_id = app_current_user_id())
    """,
]
# Statements applied by downgrade(), in order (reverse of UPGRADE).
DOWNGRADE: list[str] = [
    "DROP FUNCTION IF EXISTS app_admin_library_decide(uuid, text, text)",
    "DROP FUNCTION IF EXISTS app_admin_library_queue()",
    "DROP FUNCTION IF EXISTS app_institution_names(text, integer)",
    "DROP FUNCTION IF EXISTS app_library_report(uuid, text, text, integer)",
    "DROP INDEX IF EXISTS materials_library_item_idx",
    "ALTER TABLE materials DROP COLUMN IF EXISTS library_item_id",
    "DROP TABLE IF EXISTS library_reports",
    "DROP TABLE IF EXISTS library_items",
    "DROP FUNCTION IF EXISTS app_library_can_read(uuid, text, text, text)",
    "DROP FUNCTION IF EXISTS app_my_institution_key()",
    "DROP FUNCTION IF EXISTS app_inst_key(text)",
    "ALTER TABLE users DROP COLUMN IF EXISTS institution_name",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
