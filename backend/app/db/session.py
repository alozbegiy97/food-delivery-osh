"""Async database engine and session factory (SQLAlchemy 2.0 + psycopg 3).

Every application engine uses the explicit READ COMMITTED isolation level
(DEC-140): refresh rotation and session revocation rely on re-reading a
locked row after the competing transaction commits. The level is set on the
engine, so it does not depend on the server's `default_transaction_isolation`.
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

DB_ISOLATION_LEVEL = "READ COMMITTED"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_db_engine(url: str, **kwargs: Any) -> AsyncEngine:
    """Create an application engine with the fixed READ COMMITTED level.

    Other engine options (pool settings, `connect_args`) may be passed.
    Overriding the isolation level is refused (DEC-140).
    """
    execution_options = kwargs.get("execution_options") or {}
    if "isolation_level" in kwargs or "isolation_level" in execution_options:
        raise ValueError("isolation_level is fixed to READ COMMITTED and cannot be overridden")
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(url, isolation_level=DB_ISOLATION_LEVEL, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_db_engine(get_settings().database_url)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None  # noqa: S101 - initialised by get_engine()
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
