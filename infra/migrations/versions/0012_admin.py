"""Admin role, audit log and the read-only admin views.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# An admin never gets a way around row-level security. Instead, each admin screen is one small
# SECURITY DEFINER function that first checks app_is_admin() and then returns only what the screen
# needs: counts, names and e-mail addresses for account support, and the reported file's name and
# report reasons. No function returns a student's materials, chats, quizzes, drafts or keys.
#
# is_admin can only be changed by the table owner (the migration role, via mindnest_core.adminctl).
# A trigger refuses the application role, so a bug in the API cannot make anyone an admin.
HEAD = """
      IF NOT app_is_admin() THEN
        RAISE EXCEPTION 'admin only' USING ERRCODE = '42501';
      END IF;
"""


def _fn(signature: str, returns: str, body: str, language: str = "plpgsql", volatility: str = "") -> str:
    return f"""
    CREATE FUNCTION {signature} RETURNS {returns}
    LANGUAGE {language} {volatility} SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
    {body}
    $$
    """


UPGRADE = [
    "ALTER TABLE users ADD COLUMN is_admin boolean NOT NULL DEFAULT false",
    """
    CREATE FUNCTION users_guard_admin() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF current_user = 'mindnest_app' THEN
        IF TG_OP = 'INSERT' AND NEW.is_admin THEN
          RAISE EXCEPTION 'is_admin cannot be set by the application' USING ERRCODE = '42501';
        END IF;
        IF TG_OP = 'UPDATE' AND NEW.is_admin IS DISTINCT FROM OLD.is_admin THEN
          RAISE EXCEPTION 'is_admin cannot be changed by the application' USING ERRCODE = '42501';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER users_guard_admin BEFORE INSERT OR UPDATE ON users
      FOR EACH ROW EXECUTE FUNCTION users_guard_admin()
    """,
    """
    CREATE TABLE admin_audit_log (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      admin_id uuid REFERENCES users (id) ON DELETE SET NULL,
      action text NOT NULL,
      target_user uuid REFERENCES users (id) ON DELETE SET NULL,
      detail jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX admin_audit_created_idx ON admin_audit_log (created_at DESC)",
    # Nobody reads or writes the log directly: the default grants are taken away and the functions
    # below (which run as the table owner) are the only way in.
    "REVOKE ALL ON admin_audit_log FROM mindnest_app",
    _fn(
        "app_is_admin()",
        "boolean",
        """
        SELECT COALESCE(
          (SELECT is_admin AND status = 'active' FROM users WHERE id = app_current_user_id()), false)
        """,
        language="sql",
        volatility="STABLE",
    ),
    _fn(
        "app_admin_overview()",
        "jsonb",
        f"""
        DECLARE r jsonb;
        BEGIN{HEAD}
          SELECT jsonb_build_object(
            'users_total', (SELECT count(*) FROM users WHERE status <> 'deleted'),
            'users_active', (SELECT count(*) FROM users WHERE status = 'active'),
            'users_suspended', (SELECT count(*) FROM users WHERE status = 'suspended'),
            'users_unverified', (SELECT count(*) FROM users WHERE status = 'active' AND email_verified_at IS NULL),
            'signups_7d', (SELECT count(*) FROM users WHERE created_at > now() - interval '7 days'),
            'signups_30d', (SELECT count(*) FROM users WHERE created_at > now() - interval '30 days'),
            'active_7d', (SELECT count(DISTINCT user_id) FROM sessions WHERE last_seen_at > now() - interval '7 days'),
            'subjects', (SELECT count(*) FROM subjects),
            'materials', (SELECT count(*) FROM materials WHERE deleted_at IS NULL),
            'materials_failed', (SELECT count(*) FROM materials WHERE status = 'failed' AND deleted_at IS NULL),
            'storage_bytes', (SELECT COALESCE(sum(size_bytes), 0) FROM materials WHERE deleted_at IS NULL),
            'chunks', (SELECT count(*) FROM chunks),
            'chats_7d', (SELECT count(*) FROM messages WHERE role = 'user' AND created_at > now() - interval '7 days'),
            'ai_runs_7d', (SELECT count(*) FROM agent_runs WHERE created_at > now() - interval '7 days'),
            'ai_failed_7d', (SELECT count(*) FROM agent_runs WHERE status = 'failed' AND created_at > now() - interval '7 days'),
            'tokens_7d', (SELECT COALESCE(sum(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)), 0)
                          FROM agent_runs WHERE created_at > now() - interval '7 days'),
            'quizzes_30d', (SELECT count(*) FROM quizzes WHERE created_at > now() - interval '30 days'),
            'assignment_runs_30d', (SELECT count(*) FROM assignment_runs WHERE created_at > now() - interval '30 days'),
            'assignment_runs_failed_30d', (SELECT count(*) FROM assignment_runs
                                           WHERE status = 'failed' AND created_at > now() - interval '30 days'),
            'groups', (SELECT count(*) FROM groups),
            'shared_items', (SELECT count(*) FROM shared_items),
            'reported_items', (SELECT count(DISTINCT item_id) FROM shared_item_reports),
            'hidden_items', (SELECT count(*) FROM shared_items WHERE status = 'hidden'),
            'security_events_7d', (SELECT count(*) FROM security_events WHERE created_at > now() - interval '7 days')
          ) INTO r;
          RETURN r;
        END
        """,
    ),
    _fn(
        "app_admin_signups(p_days integer)",
        "TABLE (day date, signups integer, active_users integer)",
        f"""
        BEGIN{HEAD}
          RETURN QUERY
          SELECT d::date,
                 (SELECT count(*)::integer FROM users u WHERE u.created_at::date = d::date),
                 (SELECT count(DISTINCT s.user_id)::integer FROM sessions s WHERE s.last_seen_at::date = d::date)
          FROM generate_series(current_date - (LEAST(GREATEST(p_days, 1), 90) - 1), current_date, interval '1 day') AS d
          ORDER BY 1;
        END
        """,
    ),
    _fn(
        "app_admin_users(p_query text, p_limit integer, p_offset integer)",
        "TABLE (id uuid, email text, display_name text, status text, email_verified boolean, is_admin boolean, "
        "has_google boolean, created_at timestamptz, last_seen_at timestamptz, subjects integer, materials integer, "
        "storage_bytes bigint, messages_30d integer, total bigint)",
        f"""
        BEGIN{HEAD}
          RETURN QUERY
          SELECT u.id, u.email, u.display_name, u.status, (u.email_verified_at IS NOT NULL), u.is_admin,
                 EXISTS (SELECT 1 FROM user_identities i WHERE i.user_id = u.id),
                 u.created_at,
                 (SELECT max(s.last_seen_at) FROM sessions s WHERE s.user_id = u.id),
                 (SELECT count(*)::integer FROM subjects x WHERE x.owner_id = u.id),
                 (SELECT count(*)::integer FROM materials m WHERE m.owner_id = u.id AND m.deleted_at IS NULL),
                 (SELECT COALESCE(sum(m.size_bytes), 0)::bigint FROM materials m WHERE m.owner_id = u.id AND m.deleted_at IS NULL),
                 (SELECT count(*)::integer FROM messages ms JOIN conversations c ON c.id = ms.conversation_id
                    WHERE c.user_id = u.id AND ms.role = 'user' AND ms.created_at > now() - interval '30 days'),
                 count(*) OVER ()
          FROM users u
          WHERE u.status <> 'deleted'
            AND (p_query IS NULL OR p_query = ''
                 OR u.email ILIKE '%' || p_query || '%' ESCAPE '\\'
                 OR u.display_name ILIKE '%' || p_query || '%' ESCAPE '\\')
          ORDER BY u.created_at DESC
          LIMIT LEAST(GREATEST(p_limit, 1), 100) OFFSET GREATEST(p_offset, 0);
        END
        """,
    ),
    # Suspend or reactivate. A suspended student is signed out at once and cannot sign in.
    _fn(
        "app_admin_set_status(p_user uuid, p_status text, p_reason text)",
        "text",
        f"""
        DECLARE target record;
        BEGIN{HEAD}
          IF p_status NOT IN ('active', 'suspended') THEN
            RAISE EXCEPTION 'bad status' USING ERRCODE = '22023';
          END IF;
          SELECT id, status, is_admin INTO target FROM users WHERE id = p_user;
          IF NOT FOUND OR target.status = 'deleted' THEN RETURN NULL; END IF;
          IF p_user = app_current_user_id() OR target.is_admin THEN
            RAISE EXCEPTION 'cannot change an admin account' USING ERRCODE = '42501';
          END IF;
          UPDATE users SET status = p_status, updated_at = now() WHERE id = p_user;
          IF p_status = 'suspended' THEN DELETE FROM sessions WHERE user_id = p_user; END IF;
          INSERT INTO admin_audit_log (admin_id, action, target_user, detail)
            VALUES (app_current_user_id(), CASE p_status WHEN 'suspended' THEN 'suspend_user' ELSE 'activate_user' END,
                    p_user, jsonb_build_object('reason', left(COALESCE(p_reason, ''), 300)));
          RETURN p_status;
        END
        """,
    ),
    _fn(
        "app_admin_reports()",
        "TABLE (item_id uuid, group_id uuid, group_name text, filename text, kind text, size_bytes bigint, "
        "status text, shared_by uuid, shared_by_name text, shared_by_email text, reports integer, "
        "last_report_at timestamptz, reasons jsonb, notes jsonb, created_at timestamptz)",
        f"""
        BEGIN{HEAD}
          RETURN QUERY
          SELECT s.id, s.group_id, g.name, s.filename, s.kind, s.size_bytes, s.status, s.shared_by,
                 u.display_name, u.email,
                 (SELECT count(*)::integer FROM shared_item_reports r WHERE r.item_id = s.id),
                 (SELECT max(r.created_at) FROM shared_item_reports r WHERE r.item_id = s.id),
                 COALESCE((SELECT jsonb_object_agg(x.reason, x.n)
                             FROM (SELECT r.reason, count(*) AS n FROM shared_item_reports r
                                   WHERE r.item_id = s.id GROUP BY r.reason) x), '{{}}'::jsonb),
                 COALESCE((SELECT jsonb_agg(left(r.note, 300))
                             FROM shared_item_reports r WHERE r.item_id = s.id AND r.note <> ''), '[]'::jsonb),
                 s.created_at
          FROM shared_items s
          JOIN groups g ON g.id = s.group_id
          JOIN users u ON u.id = s.shared_by
          WHERE EXISTS (SELECT 1 FROM shared_item_reports r WHERE r.item_id = s.id)
          ORDER BY (s.status = 'hidden') DESC, 11 DESC, 12 DESC
          LIMIT 200;
        END
        """,
    ),
    # Returns the stored file's key so the API can delete it from object storage.
    _fn(
        "app_admin_remove_item(p_item uuid, p_reason text)",
        "text",
        f"""
        DECLARE k text; sharer uuid; fname text;
        BEGIN{HEAD}
          SELECT storage_key, shared_by, filename INTO k, sharer, fname FROM shared_items WHERE id = p_item;
          IF k IS NULL THEN RETURN NULL; END IF;
          DELETE FROM shared_items WHERE id = p_item;
          INSERT INTO admin_audit_log (admin_id, action, target_user, detail)
            VALUES (app_current_user_id(), 'remove_shared_file', sharer,
                    jsonb_build_object('filename', left(fname, 200), 'reason', left(COALESCE(p_reason, ''), 300)));
          RETURN k;
        END
        """,
    ),
    _fn(
        "app_admin_dismiss_reports(p_item uuid)",
        "boolean",
        f"""
        DECLARE sharer uuid; fname text;
        BEGIN{HEAD}
          SELECT shared_by, filename INTO sharer, fname FROM shared_items WHERE id = p_item;
          IF sharer IS NULL THEN RETURN false; END IF;
          DELETE FROM shared_item_reports WHERE item_id = p_item;
          UPDATE shared_items SET status = 'active' WHERE id = p_item;
          INSERT INTO admin_audit_log (admin_id, action, target_user, detail)
            VALUES (app_current_user_id(), 'dismiss_reports', sharer, jsonb_build_object('filename', left(fname, 200)));
          RETURN true;
        END
        """,
    ),
    _fn(
        "app_admin_security(p_days integer)",
        "TABLE (kind text, events bigint, students bigint)",
        f"""
        BEGIN{HEAD}
          RETURN QUERY
          SELECT e.kind, count(*), count(DISTINCT e.user_id)
          FROM security_events e
          WHERE e.created_at > now() - make_interval(days => LEAST(GREATEST(p_days, 1), 90))
          GROUP BY e.kind ORDER BY 2 DESC;
        END
        """,
    ),
    _fn(
        "app_admin_audit(p_limit integer)",
        "TABLE (id uuid, admin_name text, action text, target_email text, detail jsonb, created_at timestamptz)",
        f"""
        BEGIN{HEAD}
          RETURN QUERY
          SELECT a.id, au.display_name, a.action, tu.email, a.detail, a.created_at
          FROM admin_audit_log a
          LEFT JOIN users au ON au.id = a.admin_id
          LEFT JOIN users tu ON tu.id = a.target_user
          ORDER BY a.created_at DESC LIMIT LEAST(GREATEST(p_limit, 1), 200);
        END
        """,
    ),
    "REVOKE ALL ON FUNCTION app_is_admin(), app_admin_overview(), app_admin_signups(integer), "
    "app_admin_users(text, integer, integer), app_admin_set_status(uuid, text, text), app_admin_reports(), "
    "app_admin_remove_item(uuid, text), app_admin_dismiss_reports(uuid), app_admin_security(integer), "
    "app_admin_audit(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_is_admin(), app_admin_overview(), app_admin_signups(integer), "
    "app_admin_users(text, integer, integer), app_admin_set_status(uuid, text, text), app_admin_reports(), "
    "app_admin_remove_item(uuid, text), app_admin_dismiss_reports(uuid), app_admin_security(integer), "
    "app_admin_audit(integer) TO mindnest_app",
]

DOWNGRADE = [
    "DROP FUNCTION IF EXISTS app_admin_audit(integer)",
    "DROP FUNCTION IF EXISTS app_admin_security(integer)",
    "DROP FUNCTION IF EXISTS app_admin_dismiss_reports(uuid)",
    "DROP FUNCTION IF EXISTS app_admin_remove_item(uuid, text)",
    "DROP FUNCTION IF EXISTS app_admin_reports()",
    "DROP FUNCTION IF EXISTS app_admin_set_status(uuid, text, text)",
    "DROP FUNCTION IF EXISTS app_admin_users(text, integer, integer)",
    "DROP FUNCTION IF EXISTS app_admin_signups(integer)",
    "DROP FUNCTION IF EXISTS app_admin_overview()",
    "DROP FUNCTION IF EXISTS app_is_admin()",
    "DROP TABLE IF EXISTS admin_audit_log",
    "DROP TRIGGER IF EXISTS users_guard_admin ON users",
    "DROP FUNCTION IF EXISTS users_guard_admin()",
    "ALTER TABLE users DROP COLUMN IF EXISTS is_admin",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
