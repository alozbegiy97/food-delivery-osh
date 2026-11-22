"""Alembic environment with an async SQLAlchemy engine (psycopg 3).

Alembic is the only schema migration mechanism (no `create_all()`).
The URL comes from DATABASE_URL; it can be overridden for a single run with
`alembic -x database_url=... upgrade head` (used by migration tests).
"""

import asyncio
from logging.config import fileConfig

from geoalchemy2.alembic_helpers import render_item
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.db.models_registry import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Objects created by the PostGIS extension itself. They are not part of our
# models, so autogenerate must never propose to drop or alter them.
_POSTGIS_SYSTEM_TABLES = frozenset({"spatial_ref_sys"})


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "table" and reflected and name in _POSTGIS_SYSTEM_TABLES)


def _database_url() -> str:
    override = context.get_x_argument(as_dictionary=True).get("database_url")
    if override:
        return override
    from app.core.config import get_settings

    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        # Renders geoalchemy2 types (with their import) in autogenerate.
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
