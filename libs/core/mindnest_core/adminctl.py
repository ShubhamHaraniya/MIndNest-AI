"""Make someone an admin (or stop them being one) from the command line.

Admin rights are never granted through the website. Run this as the database owner:

    docker compose run --rm migrate python -m mindnest_core.adminctl grant you@example.com
    docker compose run --rm migrate python -m mindnest_core.adminctl revoke you@example.com
    docker compose run --rm migrate python -m mindnest_core.adminctl list

The person must already have an account with a confirmed e-mail address.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mindnest_core.db import make_engine
from mindnest_core.settings import get_settings


async def set_admin(engine: AsyncEngine, email: str, value: bool) -> str:
    """Returns a short code: 'ok', 'not_found', 'unverified' or 'inactive'."""
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT id, status, email_verified_at IS NOT NULL AS verified FROM users WHERE lower(email) = :e"),
                    {"e": email.strip().lower()},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return "not_found"
        if value and row["status"] != "active":
            return "inactive"
        if value and not row["verified"]:
            return "unverified"
        await conn.execute(text("UPDATE users SET is_admin = :v WHERE id = :id"), {"v": value, "id": row["id"]})
        await conn.execute(
            text("INSERT INTO admin_audit_log (admin_id, action, target_user, detail) VALUES (NULL, :a, :u, '{}'::jsonb)"),
            {"a": "grant_admin" if value else "revoke_admin", "u": row["id"]},
        )
    return "ok"


async def list_admins(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT email FROM users WHERE is_admin ORDER BY email"))
        return [r[0] for r in rows]


MESSAGES = {
    "not_found": "No account has that e-mail address. They need to sign up first.",
    "unverified": "That account has not confirmed its e-mail address yet.",
    "inactive": "That account is not active.",
}


async def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"grant", "revoke", "list"} or (argv[0] != "list" and len(argv) != 2):
        print(__doc__)
        return 2
    engine = make_engine(get_settings().migration_database_url)
    try:
        if argv[0] == "list":
            for email in await list_admins(engine):
                print(email)
            return 0
        result = await set_admin(engine, argv[1], argv[0] == "grant")
        if result != "ok":
            print(MESSAGES[result])
            return 1
        print(f"Done: {argv[1]} is {'now' if argv[0] == 'grant' else 'no longer'} an admin.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
