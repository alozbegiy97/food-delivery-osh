"""Shared seed infrastructure (DEC-136, DEC-137, DEC-138).

Every seed mode runs inside one transaction owned by the caller and
follows the same order: advisory lock -> strict Alembic revision check ->
mode-specific checks -> inserts. Seed functions never commit; on any
error the caller's transaction is rolled back completely.

Inserts only add missing rows: each one is `INSERT ... ON CONFLICT
(<target>) DO NOTHING` with the explicit target fixed by DEC-138. A
violation of any other constraint is not suppressed and becomes a
`SeedError`.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Table, text
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.base import Base

# DEC-138: constant UUIDv5 namespace of all seed records. NEVER CHANGE IT:
# with another value seed no longer recognises the records it created.
# Not a secret.
NAMESPACE_STR = "9001f190-2113-481c-a977-fe2b1f0212a0"
NAMESPACE = uuid.UUID(NAMESPACE_STR)

# One advisory lock key for both modes (DEC-136): parallel runs wait for
# each other instead of inserting concurrently. Fixed value, never change.
SEED_ADVISORY_LOCK_KEY = 0x5EED_0136

# alembic.ini lives in the backend root, next to the `app` package.
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# DEC-138: explicit ON CONFLICT target of every table the seed writes to.
# Each target is the table's PRIMARY KEY or one of its UNIQUE constraints.
CONFLICT_TARGETS: dict[str, tuple[str, ...]] = {
    "roles": ("name",),
    "payment_methods": ("code",),
    "restaurant_settings": ("id",),
    "restaurant_working_hours": ("weekday",),
    "delivery_zones": ("id",),
    "categories": ("id",),
    "category_translations": ("category_id", "language_code"),
    "products": ("id",),
    "product_translations": ("product_id", "language_code"),
    "product_variants": ("id",),
    "product_variant_translations": ("variant_id", "language_code"),
    "modifier_groups": ("id",),
    "modifier_group_translations": ("group_id", "language_code"),
    "modifiers": ("id",),
    "modifier_translations": ("modifier_id", "language_code"),
    "product_modifier_groups": ("product_id", "group_id"),
    "variant_modifier_prices": ("variant_id", "modifier_id"),
}

# DEC-138: code components are lowercase Latin letters, digits and hyphens;
# the dot only separates components of the final code.
_SEED_CODE_PATTERN = re.compile(r"demo(\.[a-z0-9-]+)+")


class SeedError(Exception):
    """Expected seed failure: clear message, exit code 1, full rollback."""


@dataclass
class SeedReport:
    """Per-table counters: created by this run / already existed."""

    counts: dict[str, tuple[int, int]] = field(default_factory=dict)

    def add(self, table: str, created: int, existing: int) -> None:
        old_created, old_existing = self.counts.get(table, (0, 0))
        self.counts[table] = (old_created + created, old_existing + existing)

    def created(self, table: str) -> int:
        return self.counts.get(table, (0, 0))[0]

    def existing(self, table: str) -> int:
        return self.counts.get(table, (0, 0))[1]

    def lines(self) -> list[str]:
        return [
            f"{table}: создано {created}, уже было {existing}"
            for table, (created, existing) in self.counts.items()
        ]


def seed_uuid(code: str) -> uuid.UUID:
    """Deterministic id of a demo record: `uuid5(NAMESPACE, code)` (DEC-138)."""
    if not _SEED_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"invalid seed code: {code!r}")
    return uuid.uuid5(NAMESPACE, code)


# --- Alembic revision (DEC-137 «Ревизия БД») --------------------------------


def get_migration_heads() -> list[str]:
    """Head revisions of the migration scripts (no database access)."""
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return list(script.get_heads())


async def read_alembic_versions(conn: AsyncConnection) -> list[str] | None:
    """Rows of `alembic_version`, or None when the table does not exist."""
    exists = await conn.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
    if not exists:
        return None
    result = await conn.execute(text("SELECT version_num FROM alembic_version"))
    return sorted(row[0] for row in result)


def evaluate_revision(heads: Sequence[str], versions: Sequence[str] | None) -> None:
    """Raise SeedError unless there is exactly one head and the DB is at it."""
    if len(heads) != 1:
        found = ", ".join(sorted(heads)) or "нет"
        raise SeedError(
            f"в миграциях должна быть ровно одна head-ревизия, найдено {len(heads)}: {found}"
        )
    if versions is None:
        raise SeedError(
            "в БД нет таблицы alembic_version: сначала выполните `alembic upgrade head`"
        )
    if len(versions) != 1:
        raise SeedError(f"в alembic_version должна быть ровно одна строка, найдено {len(versions)}")
    if versions[0] != heads[0]:
        raise SeedError(
            f"ревизия БД {versions[0]} не равна head {heads[0]}: "
            "сначала выполните `alembic upgrade head`"
        )


async def check_revision(conn: AsyncConnection) -> None:
    evaluate_revision(get_migration_heads(), await read_alembic_versions(conn))


# --- Transaction preparation --------------------------------------------------


async def acquire_lock(conn: AsyncConnection) -> None:
    """Transaction-level advisory lock, released on commit or rollback."""
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"),
        {"key": SEED_ADVISORY_LOCK_KEY},
    )


async def prepare_seed(conn: AsyncConnection) -> None:
    """Lock first, then verify the revision; nothing is written before both."""
    await acquire_lock(conn)
    await check_revision(conn)


# --- Inserts ------------------------------------------------------------------


def table_of(model: type[Base]) -> Table:
    table = model.__table__
    if not isinstance(table, Table):
        raise TypeError(f"{model.__name__} is not mapped to a table")
    return table


def build_insert(table: Table, rows: Sequence[Mapping[str, Any]]) -> Insert:
    """`INSERT ... ON CONFLICT (<DEC-138 target>) DO NOTHING RETURNING <pk>`."""
    target = CONFLICT_TARGETS.get(table.name)
    if not target:
        raise ValueError(f"no ON CONFLICT target is defined for table {table.name!r}")
    return (
        pg_insert(table)
        .values([dict(row) for row in rows])
        .on_conflict_do_nothing(index_elements=list(target))
        .returning(*table.primary_key.columns)
    )


async def insert_missing(
    conn: AsyncConnection,
    report: SeedReport,
    model: type[Base],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Insert rows that do not exist yet; existing rows are left untouched."""
    table = table_of(model)
    if not rows:
        report.add(table.name, 0, 0)
        return
    try:
        result = await conn.execute(build_insert(table, rows))
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        raise SeedError(
            f"нарушено ограничение БД {constraint or 'без имени'} в таблице {table.name}; "
            "изменения откатываются"
        ) from exc
    created = len(result.all())
    report.add(table.name, created, len(rows) - created)
