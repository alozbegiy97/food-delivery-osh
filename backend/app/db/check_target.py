"""Print which database DATABASE_URL really points to (no credentials).

`python -m app.db.check_target food_delivery_sandbox` exits 0 only if the
server reports exactly that database; used before migrations and seeds in
sandbox mode. Prints host, current_database() and the Alembic revision.
"""

import asyncio
import sys
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


async def _check() -> tuple[str, str | None]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            name = await conn.scalar(text("SELECT current_database()"))
            has_alembic = await conn.scalar(
                text("SELECT to_regclass('alembic_version') IS NOT NULL")
            )
            revision = (
                await conn.scalar(text("SELECT version_num FROM alembic_version"))
                if has_alembic
                else None
            )
            return str(name), revision
    finally:
        await engine.dispose()


def main() -> int:
    expected = sys.argv[1] if len(sys.argv) > 1 else None
    host = urlsplit(get_settings().database_url).hostname
    name, revision = asyncio.run(_check())
    print(f"host={host} current_database={name} alembic_revision={revision}")
    if expected is not None and name != expected:
        print(f"REFUSED: expected database {expected!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
