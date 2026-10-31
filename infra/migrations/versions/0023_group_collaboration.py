"""Study groups: admins, invitations, shared notes, discussions and study sessions.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Roles: owner (one, made with the group), admin (made by the owner) and member. Admins invite,
# remove members, hide or restore library files and moderate what members write. The same
# row-level-security rule as before holds for everything new: a row is visible only to members of
# its group (app_is_group_member), checked by a definer function so the policy cannot loop.
#
# Invitations go to an email address. The invited person cannot read the group (they are not in it
# yet), so they see and answer their invitations through definer functions that match the address
# on their own account. An invitation expires after 14 days.
UPGRADE: list[str] = [
    # --- admin role --------------------------------------------------------------------------
    "ALTER TABLE group_members DROP CONSTRAINT IF EXISTS group_members_role_check",
    "ALTER TABLE group_members ADD CONSTRAINT group_members_role_check "
    "CHECK (role IN ('owner', 'admin', 'member'))",
    """
    CREATE FUNCTION app_is_group_admin(gid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT EXISTS (
        SELECT 1 FROM group_members
        WHERE group_id = gid AND user_id = app_current_user_id() AND role IN ('owner', 'admin')
      )
    $$
    """,
    # The owner makes a member an admin or back. Returns false when nothing was changed.
    """
    CREATE FUNCTION app_set_member_role(p_group uuid, p_user uuid, p_role text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      changed integer;
    BEGIN
      IF p_role NOT IN ('admin', 'member') OR NOT app_is_group_owner(p_group) THEN RETURN false; END IF;
      UPDATE group_members SET role = p_role
        WHERE group_id = p_group AND user_id = p_user AND role <> 'owner';
      GET DIAGNOSTICS changed = ROW_COUNT;
      RETURN changed > 0;
    END
    $$
    """,
    # A student can leave; an admin removes members; the owner also removes admins. The owner
    # row can never be deleted this way.
    "DROP POLICY IF EXISTS group_members_remove ON group_members",
    """
    CREATE POLICY group_members_remove ON group_members FOR DELETE TO mindnest_app
      USING (
        (user_id = app_current_user_id() AND role IN ('member', 'admin'))
        OR (role = 'member' AND app_is_group_admin(group_id))
        OR (role = 'admin' AND app_is_group_owner(group_id))
      )
    """,
    # Admins also see hidden files and the reports on them, hide and restore files, and remove any.
    "DROP POLICY IF EXISTS shared_items_read ON shared_items",
    """
    CREATE POLICY shared_items_read ON shared_items FOR SELECT TO mindnest_app
      USING (
        app_is_group_member(group_id)
        AND (status = 'active' OR shared_by = app_current_user_id() OR app_is_group_admin(group_id))
      )
    """,
    "DROP POLICY IF EXISTS shared_items_update ON shared_items",
    """
    CREATE POLICY shared_items_update ON shared_items FOR UPDATE TO mindnest_app
      USING (app_is_group_admin(group_id)) WITH CHECK (app_is_group_admin(group_id))
    """,
    "DROP POLICY IF EXISTS shared_items_delete ON shared_items",
    """
    CREATE POLICY shared_items_delete ON shared_items FOR DELETE TO mindnest_app
      USING (shared_by = app_current_user_id() OR app_is_group_admin(group_id))
    """,
    "DROP POLICY IF EXISTS shared_item_reports_read ON shared_item_reports",
    """
    CREATE POLICY shared_item_reports_read ON shared_item_reports FOR SELECT TO mindnest_app
      USING (
        reporter_id = app_current_user_id()
        OR EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_admin(s.group_id)
        )
      )
    """,
    "DROP POLICY IF EXISTS shared_item_reports_clear ON shared_item_reports",
    """
    CREATE POLICY shared_item_reports_clear ON shared_item_reports FOR DELETE TO mindnest_app
      USING (
        EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_admin(s.group_id)
        )
      )
    """,
    # --- invitations -------------------------------------------------------------------------
    """
    CREATE TABLE group_invitations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      invited_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      email text NOT NULL,
      role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined', 'revoked')),
      created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL DEFAULT now() + interval '14 days',
      responded_at timestamptz
    )
    """,
    "CREATE UNIQUE INDEX group_invitations_pending_uq ON group_invitations (group_id, lower(email)) "
    "WHERE status = 'pending'",
    "CREATE INDEX group_invitations_email_idx ON group_invitations (lower(email)) WHERE status = 'pending'",
    # Is this address already a member of the group? Only an admin of the group may ask.
    """
    CREATE FUNCTION app_email_in_group(p_group uuid, p_email text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT app_is_group_admin(p_group) AND EXISTS (
        SELECT 1 FROM group_members m JOIN users u ON u.id = m.user_id
        WHERE m.group_id = p_group AND lower(u.email) = lower(p_email)
      )
    $$
    """,
    # The invitations waiting for the signed-in student (matched on the address of their account).
    """
    CREATE FUNCTION app_my_invitations()
    RETURNS TABLE (
      id uuid, group_id uuid, group_name text, group_description text, role text,
      invited_by_name text, created_at timestamptz, expires_at timestamptz
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
      SELECT i.id, i.group_id, g.name, g.description, i.role, u.display_name, i.created_at, i.expires_at
      FROM group_invitations i
      JOIN groups g ON g.id = i.group_id
      JOIN users u ON u.id = i.invited_by
      WHERE i.status = 'pending' AND i.expires_at > now()
        AND lower(i.email) = (SELECT lower(email) FROM users WHERE id = app_current_user_id())
      ORDER BY i.created_at DESC
    $$
    """,
    # Accept or decline one. Returns the group id, or NULL when the invitation is not (or no
    # longer) one the caller can answer.
    """
    CREATE FUNCTION app_answer_invitation(p_id uuid, p_accept boolean) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    DECLARE
      me uuid := app_current_user_id();
      inv group_invitations%ROWTYPE;
    BEGIN
      IF me IS NULL THEN RAISE EXCEPTION 'not signed in'; END IF;
      SELECT * INTO inv FROM group_invitations
        WHERE id = p_id AND status = 'pending' AND expires_at > now()
          AND lower(email) = (SELECT lower(email) FROM users WHERE id = me)
        FOR UPDATE;
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF p_accept THEN
        INSERT INTO group_members (group_id, user_id, role) VALUES (inv.group_id, me, inv.role)
          ON CONFLICT DO NOTHING;
        UPDATE group_invitations SET status = 'accepted', responded_at = now() WHERE id = inv.id;
      ELSE
        UPDATE group_invitations SET status = 'declined', responded_at = now() WHERE id = inv.id;
      END IF;
      RETURN inv.group_id;
    END
    $$
    """,
    # --- shared notes ------------------------------------------------------------------------
    """
    CREATE TABLE group_notes (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      author_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      title text NOT NULL,
      body text NOT NULL DEFAULT '',
      pinned boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX group_notes_group_idx ON group_notes (group_id, pinned DESC, updated_at DESC)",
    # --- discussions -------------------------------------------------------------------------
    """
    CREATE TABLE group_threads (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      author_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      title text NOT NULL,
      body text NOT NULL DEFAULT '',
      pinned boolean NOT NULL DEFAULT false,
      locked boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      edited_at timestamptz,
      last_activity_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX group_threads_group_idx ON group_threads (group_id, pinned DESC, last_activity_at DESC)",
    # group_id is repeated on a post so its policy can say "member of this group" without a join.
    """
    CREATE TABLE group_posts (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      thread_id uuid NOT NULL REFERENCES group_threads (id) ON DELETE CASCADE,
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      author_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      body text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      edited_at timestamptz
    )
    """,
    "CREATE INDEX group_posts_thread_idx ON group_posts (thread_id, created_at)",
    # --- study sessions ----------------------------------------------------------------------
    """
    CREATE TABLE group_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      created_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      title text NOT NULL,
      description text NOT NULL DEFAULT '',
      starts_at timestamptz NOT NULL,
      minutes integer NOT NULL DEFAULT 60 CHECK (minutes BETWEEN 15 AND 720),
      location text NOT NULL DEFAULT '',
      status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'cancelled')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX group_sessions_group_idx ON group_sessions (group_id, starts_at)",
    """
    CREATE TABLE group_session_rsvps (
      session_id uuid NOT NULL REFERENCES group_sessions (id) ON DELETE CASCADE,
      group_id uuid NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
      user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
      response text NOT NULL CHECK (response IN ('going', 'maybe', 'declined')),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (session_id, user_id)
    )
    """,
    # --- access ------------------------------------------------------------------------------
    "REVOKE ALL ON FUNCTION app_is_group_admin(uuid), app_set_member_role(uuid, uuid, text), "
    "app_email_in_group(uuid, text), app_my_invitations(), app_answer_invitation(uuid, boolean) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_is_group_admin(uuid), app_set_member_role(uuid, uuid, text), "
    "app_email_in_group(uuid, text), app_my_invitations(), app_answer_invitation(uuid, boolean) TO mindnest_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON group_invitations, group_notes, group_threads, group_posts, "
    "group_sessions, group_session_rsvps TO mindnest_app",
]

_TABLES = (
    "group_invitations", "group_notes", "group_threads", "group_posts", "group_sessions", "group_session_rsvps",
)
for _table in _TABLES:
    UPGRADE.append(f"ALTER TABLE {_table} ENABLE ROW LEVEL SECURITY")

UPGRADE += [
    # Invitations: only the group's admins read and manage them (the invited person goes through
    # the definer functions above).
    """
    CREATE POLICY group_invitations_read ON group_invitations FOR SELECT TO mindnest_app
      USING (app_is_group_admin(group_id))
    """,
    """
    CREATE POLICY group_invitations_add ON group_invitations FOR INSERT TO mindnest_app
      WITH CHECK (app_is_group_admin(group_id) AND invited_by = app_current_user_id())
    """,
    """
    CREATE POLICY group_invitations_change ON group_invitations FOR UPDATE TO mindnest_app
      USING (app_is_group_admin(group_id)) WITH CHECK (app_is_group_admin(group_id))
    """,
    """
    CREATE POLICY group_invitations_delete ON group_invitations FOR DELETE TO mindnest_app
      USING (app_is_group_admin(group_id))
    """,
    # Notes.
    """
    CREATE POLICY group_notes_read ON group_notes FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_notes_add ON group_notes FOR INSERT TO mindnest_app
      WITH CHECK (author_id = app_current_user_id() AND app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_notes_change ON group_notes FOR UPDATE TO mindnest_app
      USING (app_is_group_member(group_id) AND (author_id = app_current_user_id() OR app_is_group_admin(group_id)))
      WITH CHECK (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_notes_delete ON group_notes FOR DELETE TO mindnest_app
      USING (app_is_group_member(group_id) AND (author_id = app_current_user_id() OR app_is_group_admin(group_id)))
    """,
    # Threads.
    """
    CREATE POLICY group_threads_read ON group_threads FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_threads_add ON group_threads FOR INSERT TO mindnest_app
      WITH CHECK (author_id = app_current_user_id() AND app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_threads_change ON group_threads FOR UPDATE TO mindnest_app
      USING (app_is_group_member(group_id) AND (author_id = app_current_user_id() OR app_is_group_admin(group_id)))
      WITH CHECK (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_threads_delete ON group_threads FOR DELETE TO mindnest_app
      USING (app_is_group_member(group_id) AND (author_id = app_current_user_id() OR app_is_group_admin(group_id)))
    """,
    # Posts: an admin may delete but not rewrite what somebody else wrote.
    """
    CREATE POLICY group_posts_read ON group_posts FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_posts_add ON group_posts FOR INSERT TO mindnest_app
      WITH CHECK (author_id = app_current_user_id() AND app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_posts_change ON group_posts FOR UPDATE TO mindnest_app
      USING (author_id = app_current_user_id() AND app_is_group_member(group_id))
      WITH CHECK (author_id = app_current_user_id() AND app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_posts_delete ON group_posts FOR DELETE TO mindnest_app
      USING (app_is_group_member(group_id) AND (author_id = app_current_user_id() OR app_is_group_admin(group_id)))
    """,
    # Sessions and RSVPs.
    """
    CREATE POLICY group_sessions_read ON group_sessions FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_sessions_add ON group_sessions FOR INSERT TO mindnest_app
      WITH CHECK (created_by = app_current_user_id() AND app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_sessions_change ON group_sessions FOR UPDATE TO mindnest_app
      USING (app_is_group_member(group_id) AND (created_by = app_current_user_id() OR app_is_group_admin(group_id)))
      WITH CHECK (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_sessions_delete ON group_sessions FOR DELETE TO mindnest_app
      USING (app_is_group_member(group_id) AND (created_by = app_current_user_id() OR app_is_group_admin(group_id)))
    """,
    """
    CREATE POLICY group_session_rsvps_read ON group_session_rsvps FOR SELECT TO mindnest_app
      USING (app_is_group_member(group_id))
    """,
    """
    CREATE POLICY group_session_rsvps_mine ON group_session_rsvps FOR ALL TO mindnest_app
      USING (user_id = app_current_user_id() AND app_is_group_member(group_id))
      WITH CHECK (user_id = app_current_user_id() AND app_is_group_member(group_id))
    """,
]

DOWNGRADE: list[str] = [
    *[f"DROP TABLE IF EXISTS {t}" for t in reversed(_TABLES)],
    "DROP FUNCTION IF EXISTS app_answer_invitation(uuid, boolean)",
    "DROP FUNCTION IF EXISTS app_my_invitations()",
    "DROP FUNCTION IF EXISTS app_email_in_group(uuid, text)",
    # Back to the owner-only rules of migration 0011 (admins become ordinary members first).
    "UPDATE group_members SET role = 'member' WHERE role = 'admin'",
    "DROP POLICY IF EXISTS group_members_remove ON group_members",
    """
    CREATE POLICY group_members_remove ON group_members FOR DELETE TO mindnest_app
      USING (role = 'member' AND (user_id = app_current_user_id() OR app_is_group_owner(group_id)))
    """,
    "DROP POLICY IF EXISTS shared_items_read ON shared_items",
    """
    CREATE POLICY shared_items_read ON shared_items FOR SELECT TO mindnest_app
      USING (
        app_is_group_member(group_id)
        AND (status = 'active' OR shared_by = app_current_user_id() OR app_is_group_owner(group_id))
      )
    """,
    "DROP POLICY IF EXISTS shared_items_update ON shared_items",
    """
    CREATE POLICY shared_items_update ON shared_items FOR UPDATE TO mindnest_app
      USING (app_is_group_owner(group_id)) WITH CHECK (app_is_group_owner(group_id))
    """,
    "DROP POLICY IF EXISTS shared_items_delete ON shared_items",
    """
    CREATE POLICY shared_items_delete ON shared_items FOR DELETE TO mindnest_app
      USING (shared_by = app_current_user_id() OR app_is_group_owner(group_id))
    """,
    "DROP POLICY IF EXISTS shared_item_reports_read ON shared_item_reports",
    """
    CREATE POLICY shared_item_reports_read ON shared_item_reports FOR SELECT TO mindnest_app
      USING (
        reporter_id = app_current_user_id()
        OR EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_owner(s.group_id)
        )
      )
    """,
    "DROP POLICY IF EXISTS shared_item_reports_clear ON shared_item_reports",
    """
    CREATE POLICY shared_item_reports_clear ON shared_item_reports FOR DELETE TO mindnest_app
      USING (
        EXISTS (
          SELECT 1 FROM shared_items s WHERE s.id = shared_item_reports.item_id AND app_is_group_owner(s.group_id)
        )
      )
    """,
    "DROP FUNCTION IF EXISTS app_set_member_role(uuid, uuid, text)",
    "DROP FUNCTION IF EXISTS app_is_group_admin(uuid)",
    "ALTER TABLE group_members DROP CONSTRAINT IF EXISTS group_members_role_check",
    "ALTER TABLE group_members ADD CONSTRAINT group_members_role_check CHECK (role IN ('owner', 'member'))",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
