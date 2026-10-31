"""Study groups and the shared library inside them.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Everything here is private to the members of a group. Row-level security answers one question:
# "is the signed-in student a member (or the owner) of this group?" The answer comes from two small
# SECURITY DEFINER functions, because a policy on group_members that looked at group_members itself
# would loop. The functions only read the membership table for the current student (app.user_id).
#
# Making a group and joining one go through definer functions too: before joining, a student cannot
# see the group (so a join code cannot be looked up with a plain SELECT), and no student may insert
# membership rows for someone else.
UPGRADE = [
    """
    CREATE TABLE groups (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name text NOT NULL,
      description text NOT NULL DEFAULT '',
      join_code text NOT NULL,
      created_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX groups_join_code_idx ON groups (join_code)",
    """
    CREATE TABLE group_members (
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      role text NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
      joined_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (group_id, user_id)
    )
    """,
    "CREATE INDEX group_members_user_idx ON group_members (user_id)",
    # The shared file is a copy in object storage, so deleting the original material never breaks it.
    """
    CREATE TABLE shared_items (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      shared_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      filename text NOT NULL,
      kind text NOT NULL DEFAULT 'material'
        CHECK (kind IN ('material', 'past_paper', 'note', 'assignment')),
      mime_type text,
      size_bytes bigint,
      storage_key text NOT NULL,
      note text NOT NULL DEFAULT '',
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'hidden')),
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX shared_items_group_idx ON shared_items (group_id, created_at DESC)",
    "CREATE INDEX shared_items_sharer_idx ON shared_items (shared_by)",
    """
    CREATE TABLE shared_item_reports (
      item_id uuid NOT NULL REFERENCES shared_items (id) ON DELETE CASCADE,
      reporter_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      reason text NOT NULL CHECK (reason IN ('copyright', 'inappropriate', 'wrong_content', 'other')),
      note text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (item_id, reporter_id)
    )
    """,
    # --- who is in which group -----------------------------------------------------------------
    """
    CREATE FUNCTION app_is_group_member(gid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT EXISTS (
        SELECT 1 FROM group_members WHERE group_id = gid AND user_id = app_current_user_id()
      )
    $$
    """,
    """
    CREATE FUNCTION app_is_group_owner(gid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT EXISTS (
        SELECT 1 FROM group_members
        WHERE group_id = gid AND user_id = app_current_user_id() AND role = 'owner'
      )
    $$
    """,
    # Make a group and its first member (the owner) in one step.
    """
    CREATE FUNCTION app_create_group(p_name text, p_description text, p_code text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      me uuid := app_current_user_id();
      gid uuid;
    BEGIN
      IF me IS NULL THEN RAISE EXCEPTION 'not signed in'; END IF;
      INSERT INTO groups (name, description, join_code, created_by)
        VALUES (p_name, p_description, p_code, me) RETURNING id INTO gid;
      INSERT INTO group_members (group_id, user_id, role) VALUES (gid, me, 'owner');
      RETURN gid;
    END
    $$
    """,
    # Join with a code. Returns the group id, or NULL when the code matches nothing. The caller
    # cannot tell a wrong code from a retired one.
    """
    CREATE FUNCTION app_join_group(p_code text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      me uuid := app_current_user_id();
      gid uuid;
    BEGIN
      IF me IS NULL THEN RAISE EXCEPTION 'not signed in'; END IF;
      SELECT id INTO gid FROM groups WHERE join_code = upper(p_code);
      IF gid IS NULL THEN RETURN NULL; END IF;
      INSERT INTO group_members (group_id, user_id, role) VALUES (gid, me, 'member')
        ON CONFLICT DO NOTHING;
      RETURN gid;
    END
    $$
    """,
    # Names of the members of a group the caller belongs to (no email addresses).
    """
    CREATE FUNCTION app_group_people(gid uuid)
    RETURNS TABLE (user_id uuid, display_name text, role text, joined_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT m.user_id, u.display_name, m.role, m.joined_at
      FROM group_members m JOIN users u ON u.id = m.user_id
      WHERE m.group_id = gid AND app_is_group_member(gid)
      ORDER BY (m.role = 'owner') DESC, u.display_name
    $$
    """,
    # A member reports an item. Several different reporters hide it until the owner decides.
    """
    CREATE FUNCTION app_report_item(p_item uuid, p_reason text, p_note text, p_hide_at integer)
    RETURNS TABLE (reports integer, hidden boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      me uuid := app_current_user_id();
      gid uuid;
      sharer uuid;
      total integer;
      now_hidden boolean;
    BEGIN
      IF me IS NULL THEN RAISE EXCEPTION 'not signed in'; END IF;
      SELECT group_id, shared_by INTO gid, sharer FROM shared_items WHERE id = p_item;
      IF gid IS NULL OR NOT app_is_group_member(gid) THEN RETURN; END IF;
      IF sharer = me THEN RETURN; END IF;
      INSERT INTO shared_item_reports (item_id, reporter_id, reason, note)
        VALUES (p_item, me, p_reason, p_note)
        ON CONFLICT (item_id, reporter_id) DO UPDATE SET reason = p_reason, note = p_note;
      SELECT count(*) INTO total FROM shared_item_reports WHERE item_id = p_item;
      IF total >= p_hide_at THEN
        UPDATE shared_items SET status = 'hidden' WHERE id = p_item;
      END IF;
      SELECT (status = 'hidden') INTO now_hidden FROM shared_items WHERE id = p_item;
      RETURN QUERY SELECT total, now_hidden;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION app_is_group_member(uuid), app_is_group_owner(uuid), "
    "app_create_group(text, text, text), app_join_group(text), app_group_people(uuid), "
    "app_report_item(uuid, text, text, integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_is_group_member(uuid), app_is_group_owner(uuid), "
    "app_create_group(text, text, text), app_join_group(text), app_group_people(uuid), "
    "app_report_item(uuid, text, text, integer) TO mindnest_app",
    # --- table access --------------------------------------------------------------------------
    # No INSERT on groups or group_members: only the functions above add rows to them.
    "GRANT SELECT, UPDATE, DELETE ON groups TO mindnest_app",
    "GRANT SELECT, DELETE ON group_members TO mindnest_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON shared_items TO mindnest_app",
    "GRANT SELECT, DELETE ON shared_item_reports TO mindnest_app",
    "ALTER TABLE groups ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE group_members ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE shared_items ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE shared_item_reports ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY groups_member_read ON groups FOR SELECT TO mindnest_app
      USING (app_is_group_member(id))
    """,
    """
    CREATE POLICY groups_owner_update ON groups FOR UPDATE TO mindnest_app
      USING (app_is_group_owner(id)) WITH CHECK (app_is_group_owner(id))
    """,
    """
    CREATE POLICY groups_owner_delete ON groups FOR DELETE TO mindnest_app
      USING (app_is_group_owner(id))
    """,
    """
    CREATE POLICY group_members_read ON group_members FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    # A student can leave; an owner can remove anyone else. Owners cannot be removed this way.
    """
    CREATE POLICY group_members_remove ON group_members FOR DELETE TO mindnest_app
      USING (role = 'member' AND (user_id = app_current_user_id() OR app_is_group_owner(group_id)))
    """,
    # Members see active items. The sharer and the owner also see hidden ones.
    """
    CREATE POLICY shared_items_read ON shared_items FOR SELECT TO mindnest_app
      USING (
        app_is_group_member(group_id)
        AND (status = 'active' OR shared_by = app_current_user_id() OR app_is_group_owner(group_id))
      )
    """,
    """
    CREATE POLICY shared_items_add ON shared_items FOR INSERT TO mindnest_app
      WITH CHECK (shared_by = app_current_user_id() AND app_is_group_member(group_id))
    """,
    # Only the owner hides or restores. (A sharer must not be able to un-hide their own reported file.)
    """
    CREATE POLICY shared_items_update ON shared_items FOR UPDATE TO mindnest_app
      USING (app_is_group_owner(group_id)) WITH CHECK (app_is_group_owner(group_id))
    """,
    """
    CREATE POLICY shared_items_delete ON shared_items FOR DELETE TO mindnest_app
      USING (shared_by = app_current_user_id() OR app_is_group_owner(group_id))
    """,
    # Reporters see their own report; the group owner sees all reports on the group's items.
    """
    CREATE POLICY shared_item_reports_read ON shared_item_reports FOR SELECT TO mindnest_app
      USING (
        reporter_id = app_current_user_id()
        OR EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_owner(s.group_id)
        )
      )
    """,
    """
    CREATE POLICY shared_item_reports_clear ON shared_item_reports FOR DELETE TO mindnest_app
      USING (
        EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_owner(s.group_id)
        )
      )
    """,
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS shared_item_reports",
    "DROP TABLE IF EXISTS shared_items",
    "DROP TABLE IF EXISTS group_members",
    "DROP TABLE IF EXISTS groups",
    "DROP FUNCTION IF EXISTS app_report_item(uuid, text, text, integer)",
    "DROP FUNCTION IF EXISTS app_group_people(uuid)",
    "DROP FUNCTION IF EXISTS app_join_group(text)",
    "DROP FUNCTION IF EXISTS app_create_group(text, text, text)",
    "DROP FUNCTION IF EXISTS app_is_group_owner(uuid)",
    "DROP FUNCTION IF EXISTS app_is_group_member(uuid)",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
