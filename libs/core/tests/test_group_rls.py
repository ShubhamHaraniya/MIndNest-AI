"""Group isolation at the database level, with no API in between.

These speak to Postgres as the application role, the same way the API does, so they prove that
row-level security (and not just the API's own checks) keeps a group's rows away from outsiders.
"""

import uuid

import pytest
import pytest_asyncio
from mindnest_core.db import make_engine, make_session_factory, user_session
from mindnest_core.settings import get_settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest_asyncio.fixture
async def world():
    settings = get_settings()
    admin = make_engine(settings.migration_database_url)
    app = make_engine(settings.database_url)
    try:
        async with admin.connect() as conn:
            await conn.execute(text("SELECT 1 FROM shared_items LIMIT 1"))
    except Exception as exc:
        await admin.dispose()
        await app.dispose()
        pytest.skip(f"migrated database not available: {exc}")
    owner, member, outsider = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with admin.begin() as conn:
        for user_id in (owner, member, outsider):
            await conn.execute(
                text("INSERT INTO users (id, email, password_hash, display_name) VALUES (:id, :e, 'x', :n)"),
                {"id": user_id, "e": f"{user_id}@test.local", "n": f"User {str(user_id)[:4]}"},
            )
    factory = make_session_factory(app)
    async with user_session(factory, owner) as session:
        gid = (
            await session.execute(text("SELECT app_create_group('Class', '', :c)"), {"c": uuid.uuid4().hex[:10].upper()})
        ).scalar_one()
    async with admin.begin() as conn:
        code = (await conn.execute(text("SELECT join_code FROM groups WHERE id = :g"), {"g": gid})).scalar_one()
    async with user_session(factory, member) as session:
        assert (await session.execute(text("SELECT app_join_group(:c)"), {"c": code})).scalar_one() == gid
    async with user_session(factory, owner) as session:
        item = (
            await session.execute(
                text(
                    "INSERT INTO shared_items (group_id, shared_by, filename, storage_key) "
                    "VALUES (:g, :u, 'n.md', 'shared/k') RETURNING id"
                ),
                {"g": gid, "u": owner},
            )
        ).scalar_one()
    yield factory, gid, item, code, owner, member, outsider
    async with admin.begin() as conn:
        await conn.execute(
            text("DELETE FROM users WHERE id IN (:a, :b, :c)"), {"a": owner, "b": member, "c": outsider}
        )
    await admin.dispose()
    await app.dispose()


async def count(factory, user, query, **params):
    async with user_session(factory, user) as session:
        return (await session.execute(text(query), params)).scalar_one()


async def test_members_see_the_group_and_outsiders_see_nothing(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    for table in ("groups", "group_members", "shared_items"):
        assert await count(factory, owner, f"SELECT count(*) FROM {table}") >= 1
        assert await count(factory, member, f"SELECT count(*) FROM {table}") >= 1
        assert await count(factory, outsider, f"SELECT count(*) FROM {table}") == 0, table


async def test_no_user_context_sees_no_groups(world) -> None:
    factory, *_ = world
    async with factory() as session:
        for table in ("groups", "group_members", "shared_items", "shared_item_reports"):
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


async def test_nobody_can_insert_a_membership_directly(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    for who in (owner, outsider):
        with pytest.raises(DBAPIError):
            async with user_session(factory, who) as session:
                await session.execute(
                    text("INSERT INTO group_members (group_id, user_id, role) VALUES (:g, :u, 'owner')"),
                    {"g": gid, "u": outsider},
                )


async def test_nobody_can_insert_a_group_directly(world) -> None:
    factory, _, _, _, _, _, outsider = world
    with pytest.raises(DBAPIError):
        async with user_session(factory, outsider) as session:
            await session.execute(
                text("INSERT INTO groups (name, join_code, created_by) VALUES ('x', 'ZZZZZZZZZZ', :u)"),
                {"u": outsider},
            )


async def test_an_outsider_cannot_put_a_file_in_a_group(world) -> None:
    factory, gid, _, _, _, _, outsider = world
    with pytest.raises(DBAPIError):
        async with user_session(factory, outsider) as session:
            await session.execute(
                text("INSERT INTO shared_items (group_id, shared_by, filename, storage_key) VALUES (:g, :u, 'x', 'k')"),
                {"g": gid, "u": outsider},
            )


async def test_a_member_cannot_share_in_someone_elses_name(world) -> None:
    factory, gid, _, _, owner, member, _ = world
    with pytest.raises(DBAPIError):
        async with user_session(factory, member) as session:
            await session.execute(
                text("INSERT INTO shared_items (group_id, shared_by, filename, storage_key) VALUES (:g, :u, 'x', 'k')"),
                {"g": gid, "u": owner},
            )


async def test_only_the_owner_can_change_or_delete_the_group(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    for who in (member, outsider):
        async with user_session(factory, who) as session:
            changed = await session.execute(text("UPDATE groups SET name = 'hijack' WHERE id = :g"), {"g": gid})
            deleted = await session.execute(text("DELETE FROM groups WHERE id = :g"), {"g": gid})
            assert changed.rowcount == 0 and deleted.rowcount == 0
    assert await count(factory, owner, "SELECT count(*) FROM groups WHERE name = 'Class'") == 1


async def test_a_sharer_cannot_unhide_their_own_file_but_the_owner_can(world) -> None:
    factory, gid, item, _, owner, member, _ = world
    async with user_session(factory, member) as session:
        await session.execute(
            text("INSERT INTO shared_items (id, group_id, shared_by, filename, storage_key, status) "
                 "VALUES (:i, :g, :u, 'm.md', 'shared/m', 'hidden')"),
            {"i": uuid.uuid4(), "g": gid, "u": member},
        )
    async with user_session(factory, member) as session:
        result = await session.execute(text("UPDATE shared_items SET status = 'active' WHERE shared_by = :u"), {"u": member})
        assert result.rowcount == 0
    async with user_session(factory, owner) as session:
        result = await session.execute(text("UPDATE shared_items SET status = 'active' WHERE shared_by = :u"), {"u": member})
        assert result.rowcount == 1


async def test_only_a_member_can_report_and_reports_stay_private(world) -> None:
    factory, gid, item, _, owner, member, outsider = world
    async with user_session(factory, outsider) as session:
        assert (await session.execute(text("SELECT count(*) FROM app_report_item(:i, 'other', '', 3)"), {"i": item})).scalar_one() == 0
    async with user_session(factory, member) as session:
        row = (await session.execute(text("SELECT * FROM app_report_item(:i, 'other', 'secret', 3)"), {"i": item})).one()
        assert row.reports == 1 and row.hidden is False
    assert await count(factory, outsider, "SELECT count(*) FROM shared_item_reports") == 0
    assert await count(factory, member, "SELECT count(*) FROM shared_item_reports") == 1
    assert await count(factory, owner, "SELECT count(*) FROM shared_item_reports") == 1
    async with user_session(factory, member) as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("INSERT INTO shared_item_reports (item_id, reporter_id, reason) VALUES (:i, :u, 'other')"), {"i": item, "u": member})


async def test_the_member_list_function_answers_only_to_members(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    assert await count(factory, member, "SELECT count(*) FROM app_group_people(:g)", g=gid) == 2
    assert await count(factory, outsider, "SELECT count(*) FROM app_group_people(:g)", g=gid) == 0


async def test_joining_with_an_unknown_code_returns_nothing(world) -> None:
    factory, _, _, _, _, _, outsider = world
    async with user_session(factory, outsider) as session:
        assert (await session.execute(text("SELECT app_join_group('NOSUCHCODE')"))).scalar_one() is None
    assert await count(factory, outsider, "SELECT count(*) FROM group_members") == 0


async def test_the_owner_cannot_be_removed_by_leaving(world) -> None:
    factory, gid, _, _, owner, *_ = world
    async with user_session(factory, owner) as session:
        result = await session.execute(text("DELETE FROM group_members WHERE group_id = :g AND user_id = :u"), {"g": gid, "u": owner})
        assert result.rowcount == 0


# ------------------------------------------------------------------ admins, invitations and what members write


async def make_note(factory, user, gid):
    async with user_session(factory, user) as session:
        return (
            await session.execute(
                text("INSERT INTO group_notes (group_id, author_id, title) VALUES (:g, :u, 'Week 1') RETURNING id"),
                {"g": gid, "u": user},
            )
        ).scalar_one()


async def test_what_members_write_is_private_to_the_group(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    note = await make_note(factory, owner, gid)
    async with user_session(factory, member) as session:
        thread = (
            await session.execute(
                text("INSERT INTO group_threads (group_id, author_id, title) VALUES (:g, :u, 'Q') RETURNING id"),
                {"g": gid, "u": member},
            )
        ).scalar_one()
        await session.execute(
            text("INSERT INTO group_posts (thread_id, group_id, author_id, body) VALUES (:t, :g, :u, 'hi')"),
            {"t": thread, "g": gid, "u": member},
        )
        await session.execute(
            text(
                "INSERT INTO group_sessions (group_id, created_by, title, starts_at) "
                "VALUES (:g, :u, 'Revision', now() + interval '1 day')"
            ),
            {"g": gid, "u": member},
        )
    for table in ("group_notes", "group_threads", "group_posts", "group_sessions"):
        assert await count(factory, member, f"SELECT count(*) FROM {table} WHERE group_id = :g", g=gid) >= 1, table
        assert await count(factory, outsider, f"SELECT count(*) FROM {table}") == 0, table
    for query in (
        "INSERT INTO group_notes (group_id, author_id, title) VALUES (:g, :u, 'x')",
        "INSERT INTO group_threads (group_id, author_id, title) VALUES (:g, :u, 'x')",
    ):
        with pytest.raises(DBAPIError):
            async with user_session(factory, outsider) as session:
                await session.execute(text(query), {"g": gid, "u": outsider})
    assert note is not None


async def test_a_member_cannot_write_in_someone_elses_name(world) -> None:
    factory, gid, _, _, owner, member, _ = world
    with pytest.raises(DBAPIError):
        async with user_session(factory, member) as session:
            await session.execute(
                text("INSERT INTO group_notes (group_id, author_id, title) VALUES (:g, :u, 'x')"),
                {"g": gid, "u": owner},
            )


async def test_only_the_author_or_an_admin_changes_a_note(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    note = await make_note(factory, member, gid)
    async with user_session(factory, outsider) as session:
        assert (await session.execute(text("UPDATE group_notes SET title = 'x' WHERE id = :i"), {"i": note})).rowcount == 0
    third = uuid.uuid4()
    admin = make_engine(get_settings().migration_database_url)
    try:
        async with admin.begin() as conn:
            await conn.execute(
                text("INSERT INTO users (id, email, password_hash, display_name) VALUES (:id, :e, 'x', 'Third')"),
                {"id": third, "e": f"{third}@test.local"},
            )
            await conn.execute(
                text("INSERT INTO group_members (group_id, user_id, role) VALUES (:g, :u, 'member')"),
                {"g": gid, "u": third},
            )
        async with user_session(factory, third) as session:
            assert (await session.execute(text("UPDATE group_notes SET pinned = true WHERE id = :i"), {"i": note})).rowcount == 0
            assert (await session.execute(text("DELETE FROM group_notes WHERE id = :i"), {"i": note})).rowcount == 0
        async with user_session(factory, owner) as session:
            assert (await session.execute(text("UPDATE group_notes SET pinned = true WHERE id = :i"), {"i": note})).rowcount == 1
            assert (
                await session.execute(text("SELECT app_set_member_role(:g, :u, 'admin')"), {"g": gid, "u": third})
            ).scalar_one() is True
        async with user_session(factory, third) as session:
            assert (await session.execute(text("UPDATE group_notes SET pinned = false WHERE id = :i"), {"i": note})).rowcount == 1
            assert (await session.execute(text("DELETE FROM group_notes WHERE id = :i"), {"i": note})).rowcount == 1
    finally:
        async with admin.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": third})
        await admin.dispose()


async def test_only_the_owner_can_set_roles_and_never_on_the_owner(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    for who in (member, outsider):
        async with user_session(factory, who) as session:
            assert (
                await session.execute(text("SELECT app_set_member_role(:g, :u, 'admin')"), {"g": gid, "u": member})
            ).scalar_one() is False
    async with user_session(factory, owner) as session:
        assert (
            await session.execute(text("SELECT app_set_member_role(:g, :u, 'member')"), {"g": gid, "u": owner})
        ).scalar_one() is False
        assert (
            await session.execute(text("SELECT app_set_member_role(:g, :u, 'owner')"), {"g": gid, "u": member})
        ).scalar_one() is False
        assert await count(factory, owner, "SELECT role FROM group_members WHERE user_id = :u", u=owner) == "owner"


async def test_an_invitation_is_visible_to_the_invited_address_only(world) -> None:
    factory, gid, _, _, owner, member, outsider = world
    async with user_session(factory, owner) as session:
        invitation = (
            await session.execute(
                text(
                    "INSERT INTO group_invitations (group_id, invited_by, email) VALUES (:g, :u, :e) RETURNING id"
                ),
                {"g": gid, "u": owner, "e": f"{outsider}@TEST.local"},  # case does not matter
            )
        ).scalar_one()
    # A plain member cannot read invitations; the invited student cannot read the table either.
    assert await count(factory, member, "SELECT count(*) FROM group_invitations") == 0
    assert await count(factory, outsider, "SELECT count(*) FROM group_invitations") == 0
    assert await count(factory, outsider, "SELECT count(*) FROM app_my_invitations()") == 1
    assert await count(factory, member, "SELECT count(*) FROM app_my_invitations()") == 0
    # Somebody else cannot answer it; the invited student can, and joins.
    assert await count(factory, member, "SELECT app_answer_invitation(:i, true)", i=invitation) is None
    assert await count(factory, outsider, "SELECT app_answer_invitation(:i, true)", i=invitation) == gid
    assert await count(factory, outsider, "SELECT count(*) FROM group_members WHERE group_id = :g", g=gid) >= 1
    assert await count(factory, outsider, "SELECT app_answer_invitation(:i, true)", i=invitation) is None  # once only


async def test_an_expired_or_declined_invitation_cannot_be_accepted(world) -> None:
    factory, gid, _, _, owner, _, outsider = world
    async with user_session(factory, owner) as session:
        old = (
            await session.execute(
                text(
                    "INSERT INTO group_invitations (group_id, invited_by, email, expires_at) "
                    "VALUES (:g, :u, :e, now() - interval '1 day') RETURNING id"
                ),
                {"g": gid, "u": owner, "e": f"{outsider}@test.local"},
            )
        ).scalar_one()
    assert await count(factory, outsider, "SELECT count(*) FROM app_my_invitations()") == 0
    assert await count(factory, outsider, "SELECT app_answer_invitation(:i, true)", i=old) is None
    async with user_session(factory, owner) as session:
        # The database still holds the lapsed invitation as "pending" (the unique index cannot look at
        # the clock), so the API closes it before it writes a new one; do the same here.
        await session.execute(text("UPDATE group_invitations SET status = 'revoked' WHERE id = :i"), {"i": old})
        fresh = (
            await session.execute(
                text("INSERT INTO group_invitations (group_id, invited_by, email) VALUES (:g, :u, :e) RETURNING id"),
                {"g": gid, "u": owner, "e": f"{outsider}@test.local"},
            )
        ).scalar_one()
    assert await count(factory, outsider, "SELECT app_answer_invitation(:i, false)", i=fresh) == gid
    assert await count(factory, outsider, "SELECT app_answer_invitation(:i, true)", i=fresh) is None
    assert await count(factory, outsider, "SELECT count(*) FROM groups") == 0  # declined: still outside


async def test_a_member_cannot_make_an_invitation(world) -> None:
    factory, gid, _, _, owner, member, _ = world
    with pytest.raises(DBAPIError):
        async with user_session(factory, member) as session:
            await session.execute(
                text("INSERT INTO group_invitations (group_id, invited_by, email) VALUES (:g, :u, 'a@b.com')"),
                {"g": gid, "u": member},
            )
