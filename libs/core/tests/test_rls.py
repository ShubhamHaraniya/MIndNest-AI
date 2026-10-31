"""Cross-user isolation tests against a real, migrated Postgres.

These skip themselves when the database is not reachable or not migrated. To run them:
start Postgres, run `alembic upgrade head`, then `pytest libs/core/tests/test_rls.py`.
"""

import uuid

import pytest
import pytest_asyncio
from mindnest_core.db import make_engine, make_session_factory, user_session
from mindnest_core.settings import get_settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest_asyncio.fixture
async def engines():
    settings = get_settings()
    admin = make_engine(settings.migration_database_url)
    app = make_engine(settings.database_url)
    try:
        async with admin.connect() as conn:
            await conn.execute(text("SELECT 1 FROM subjects LIMIT 1"))
    except Exception as exc:
        await admin.dispose()
        await app.dispose()
        pytest.skip(f"migrated database not available: {exc}")
    yield admin, app
    await admin.dispose()
    await app.dispose()


@pytest_asyncio.fixture
async def two_users(engines):
    admin, _ = engines
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    async with admin.begin() as conn:
        for user_id in (user_a, user_b):
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name) "
                    "VALUES (:id, :email, 'x', 'Test user')"
                ),
                {"id": user_id, "email": f"{user_id}@test.local"},
            )
        subject_id = (
            await conn.execute(
                text(
                    "INSERT INTO subjects (owner_id, name) VALUES (:owner, 'Operating Systems') "
                    "RETURNING id"
                ),
                {"owner": user_a},
            )
        ).scalar_one()
        material_id = (
            await conn.execute(
                text(
                    "INSERT INTO materials (subject_id, owner_id, filename, storage_key) "
                    "VALUES (:subject, :owner, 'os.pdf', 'k/os.pdf') RETURNING id"
                ),
                {"subject": subject_id, "owner": user_a},
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO chunks (material_id, subject_id, owner_id, page, text) "
                "VALUES (:material, :subject, :owner, 1, 'Process scheduling basics')"
            ),
            {"material": material_id, "subject": subject_id, "owner": user_a},
        )
    yield user_a, user_b
    async with admin.begin() as conn:
        await conn.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": user_a, "b": user_b}
        )


async def count_rows(factory, user_id, table: str) -> int:
    async with user_session(factory, user_id) as session:
        return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_owner_sees_own_rows(engines, two_users) -> None:
    _, app = engines
    factory = make_session_factory(app)
    user_a, _ = two_users
    assert await count_rows(factory, user_a, "subjects") == 1
    assert await count_rows(factory, user_a, "materials") == 1
    assert await count_rows(factory, user_a, "chunks") == 1


async def test_other_user_sees_nothing(engines, two_users) -> None:
    _, app = engines
    factory = make_session_factory(app)
    _, user_b = two_users
    for table in ("subjects", "materials", "chunks", "conversations", "agent_runs"):
        assert await count_rows(factory, user_b, table) == 0, table


async def test_no_user_context_sees_nothing(engines, two_users) -> None:
    _, app = engines
    factory = make_session_factory(app)
    async with factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM subjects"))).scalar_one() == 0
        assert (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one() == 0


async def test_user_cannot_write_rows_owned_by_someone_else(engines, two_users) -> None:
    _, app = engines
    factory = make_session_factory(app)
    user_a, user_b = two_users
    with pytest.raises(DBAPIError):
        async with user_session(factory, user_b) as session:
            await session.execute(
                text("INSERT INTO subjects (owner_id, name) VALUES (:owner, 'Sneaky')"),
                {"owner": user_a},
            )


async def test_app_role_cannot_read_eval_schema(engines, two_users) -> None:
    _, app = engines
    factory = make_session_factory(app)
    user_a, _ = two_users
    with pytest.raises(DBAPIError):
        async with user_session(factory, user_a) as session:
            await session.execute(text("SELECT count(*) FROM eval.datasets"))
