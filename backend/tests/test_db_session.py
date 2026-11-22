"""Explicit READ COMMITTED isolation of application engines (DEC-140, DB-A).

Database tests run only on the isolated `db-test` (`verify_test_database`)
and only read `SHOW transaction_isolation` / `current_database()`; they
write nothing.
"""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import (
    DB_ISOLATION_LEVEL,
    create_db_engine,
    dispose_engine,
    get_engine,
    get_session,
)
from tests.conftest import TEST_DATABASE_URL, verify_test_database

# Server-side default that the explicit engine level must override.
SERIALIZABLE_DEFAULT = {"options": "-c default_transaction_isolation=serializable"}


async def _level(conn: AsyncConnection) -> str:
    return (await conn.execute(text("SHOW transaction_isolation"))).scalar_one()


@pytest.fixture
async def serializable_default_engine() -> AsyncIterator[AsyncEngine]:
    verify_test_database()
    engine = create_db_engine(
        TEST_DATABASE_URL or "", poolclass=NullPool, connect_args=SERIALIZABLE_DEFAULT
    )
    yield engine
    await engine.dispose()


def test_isolation_level_constant() -> None:
    assert DB_ISOLATION_LEVEL == "READ COMMITTED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"isolation_level": "SERIALIZABLE"},
        {"isolation_level": "READ COMMITTED"},
        {"execution_options": {"isolation_level": "REPEATABLE READ"}},
    ],
)
def test_create_db_engine_refuses_isolation_override(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="isolation_level"):
        create_db_engine(TEST_DATABASE_URL or "postgresql+psycopg://u@127.0.0.1:1/x", **kwargs)


@pytest.mark.db
async def test_control_server_default_is_serializable_without_explicit_level() -> None:
    """Control: proves the `options` trick really changes the server default,
    so the tests below are not vacuous."""
    verify_test_database()
    engine = create_async_engine(
        TEST_DATABASE_URL or "", poolclass=NullPool, connect_args=SERIALIZABLE_DEFAULT
    )
    try:
        async with engine.connect() as conn:
            assert await _level(conn) == "serializable"
    finally:
        await engine.dispose()


@pytest.mark.db
async def test_connection_transaction_is_read_committed(
    serializable_default_engine: AsyncEngine,
) -> None:
    async with serializable_default_engine.connect() as conn:
        assert await _level(conn) == "read committed"
        await conn.rollback()
    async with serializable_default_engine.begin() as conn:
        assert await _level(conn) == "read committed"


@pytest.mark.db
async def test_session_begin_is_read_committed(serializable_default_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(serializable_default_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        level = (await session.execute(text("SHOW transaction_isolation"))).scalar_one()
    assert level == "read committed"


@pytest.mark.db
async def test_pooled_connection_returns_to_read_committed() -> None:
    """A per-connection override is reset when the connection goes back to
    the pool, so the next checkout is READ COMMITTED again."""
    verify_test_database()
    engine = create_db_engine(
        TEST_DATABASE_URL or "", pool_size=1, max_overflow=0, connect_args=SERIALIZABLE_DEFAULT
    )
    try:
        async with engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="SERIALIZABLE")
            assert await _level(conn) == "serializable"
        async with engine.connect() as conn:
            assert await _level(conn) == "read committed"
    finally:
        await engine.dispose()


@pytest.mark.db
async def test_global_engine_and_session_dependency_use_test_db_read_committed() -> None:
    verify_test_database()
    expected_db = urlsplit(TEST_DATABASE_URL or "").path.lstrip("/")
    get_settings.cache_clear()
    await dispose_engine()
    try:
        async with get_engine().connect() as conn:
            current_db = (await conn.execute(text("SELECT current_database()"))).scalar_one()
            assert current_db == expected_db
            assert await _level(conn) == "read committed"

        dependency = get_session()
        session = await anext(dependency)
        try:
            async with session.begin():
                current_db = (await session.execute(text("SELECT current_database()"))).scalar_one()
                level = (await session.execute(text("SHOW transaction_isolation"))).scalar_one()
        finally:
            await dependency.aclose()
        assert current_db == expected_db
        assert level == "read committed"
    finally:
        await dispose_engine()
