"""Shared seed infrastructure (DEC-136, DEC-137, DEC-138).

Pure tests need no database. Tests marked `db` run only on the isolated
`db-test` inside a transaction that is always rolled back (`seed_conn`).
"""

import uuid

import pytest
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.base import Base
from app.modules.restaurant.models import RestaurantWorkingHours
from app.modules.users.models import User
from app.seeds import common
from app.seeds.common import (
    CONFLICT_TARGETS,
    NAMESPACE,
    NAMESPACE_STR,
    SEED_ADVISORY_LOCK_KEY,
    SeedError,
    SeedReport,
    build_insert,
    check_revision,
    evaluate_revision,
    get_migration_heads,
    insert_missing,
    read_alembic_versions,
    seed_uuid,
    table_of,
)

# DEC-138, «Цели ON CONFLICT»: copied from the approved decision text.
DEC_138_TARGETS = {
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


# --- UUIDv5 (DEC-138) ---------------------------------------------------------


def test_namespace_is_the_approved_constant() -> None:
    assert NAMESPACE_STR == "9001f190-2113-481c-a977-fe2b1f0212a0"
    assert isinstance(NAMESPACE, uuid.UUID)
    assert str(NAMESPACE) == NAMESPACE_STR


@pytest.mark.parametrize(
    "code",
    [
        "demo.zone.osh",
        "demo.category.pizza",
        "demo.product.pizza-margherita",
        "demo.variant.pizza-margherita.30",
        "demo.group.pizza-dough",
        "demo.modifier.pizza-extras.cheese",
        "demo.translation.category.pizza.ru",
        "demo.translation.product.pizza-margherita.ky",
        "demo.translation.variant.pizza-margherita.30.uz",
        "demo.translation.group.pizza-dough.ru",
        "demo.translation.modifier.pizza-extras.cheese.ky",
    ],
)
def test_seed_uuid_is_uuid5_of_namespace(code: str) -> None:
    expected = uuid.uuid5(uuid.UUID("9001f190-2113-481c-a977-fe2b1f0212a0"), code)
    assert seed_uuid(code) == expected
    assert seed_uuid(code) == seed_uuid(code)
    assert seed_uuid(code).version == 5


def test_seed_uuid_differs_per_code() -> None:
    codes = ["demo.modifier.pizza-extras.cheese", "demo.modifier.burger-extras.cheese"]
    assert len({seed_uuid(code) for code in codes}) == 2


@pytest.mark.parametrize(
    "code",
    [
        "",
        "demo",
        "pizza",
        "zone.osh",
        "demo.",
        "demo..osh",
        "demo.zone.Osh",
        "demo.zone_osh",
        "demo.zone.osh ",
        "demo.zone.ош",
    ],
)
def test_seed_uuid_rejects_invalid_codes(code: str) -> None:
    with pytest.raises(ValueError, match="invalid seed code"):
        seed_uuid(code)


# --- ON CONFLICT targets (DEC-138) ---------------------------------------------


def test_conflict_targets_match_dec_138() -> None:
    assert CONFLICT_TARGETS == DEC_138_TARGETS


@pytest.mark.parametrize("table_name", sorted(DEC_138_TARGETS))
def test_conflict_target_is_primary_key_or_unique(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    target = set(CONFLICT_TARGETS[table_name])
    keys = [{column.name for column in table.primary_key.columns}]
    keys += [
        {column.name for column in constraint.columns}
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    keys += [{column.name for column in index.columns} for index in table.indexes if index.unique]
    assert target in keys, f"{table_name}: {sorted(target)} is neither PK nor UNIQUE"


@pytest.mark.parametrize("table_name", sorted(DEC_138_TARGETS))
def test_insert_uses_explicit_target(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    row = {column.name: None for column in table.columns}
    sql = " ".join(str(build_insert(table, [row]).compile(dialect=postgresql.dialect())).split())
    target = ", ".join(CONFLICT_TARGETS[table_name])
    assert f"ON CONFLICT ({target}) DO NOTHING" in sql
    assert "ON CONFLICT DO NOTHING" not in sql
    assert sql.count("ON CONFLICT") == 1


def test_insert_without_target_is_refused() -> None:
    with pytest.raises(ValueError, match="no ON CONFLICT target"):
        build_insert(table_of(User), [{"email": "x@example.com"}])


# --- Alembic revision (DEC-137) -------------------------------------------------


def test_evaluate_revision_accepts_single_matching_head() -> None:
    evaluate_revision(["0008_notifications"], ["0008_notifications"])


@pytest.mark.parametrize(
    ("heads", "versions", "message"),
    [
        ([], ["0008_notifications"], "ровно одна head-ревизия, найдено 0"),
        (["0008_a", "0008_b"], ["0008_a"], "ровно одна head-ревизия, найдено 2"),
        (["0008_notifications"], None, "нет таблицы alembic_version"),
        (["0008_notifications"], [], "ровно одна строка, найдено 0"),
        (["0008_notifications"], ["0007_x", "0008_notifications"], "ровно одна строка, найдено 2"),
        (["0008_notifications"], ["0007_payments_deliveries"], "не равна head"),
    ],
)
def test_evaluate_revision_rejects(
    heads: list[str], versions: list[str] | None, message: str
) -> None:
    with pytest.raises(SeedError, match=message):
        evaluate_revision(heads, versions)


def test_migrations_have_exactly_one_head() -> None:
    assert len(get_migration_heads()) == 1


@pytest.mark.db
async def test_test_database_is_at_head(seed_conn: AsyncConnection) -> None:
    assert await read_alembic_versions(seed_conn) == get_migration_heads()
    await check_revision(seed_conn)


# --- Report, inserts, lock ------------------------------------------------------


def test_report_counts_and_lines() -> None:
    report = SeedReport()
    report.add("roles", 3, 1)
    report.add("roles", 0, 0)
    report.add("payment_methods", 0, 2)
    assert report.created("roles") == 3
    assert report.existing("roles") == 1
    assert report.lines() == [
        "roles: создано 3, уже было 1",
        "payment_methods: создано 0, уже было 2",
    ]


@pytest.mark.db
async def test_constraint_violation_becomes_seed_error(seed_conn: AsyncConnection) -> None:
    """Only the declared target is suppressed; a CHECK violation is an error."""
    bad_row = {"weekday": 9, "opens_at": None, "closes_at": None, "is_closed": True}
    with pytest.raises(SeedError, match="restaurant_working_hours"):
        await insert_missing(seed_conn, SeedReport(), RestaurantWorkingHours, [bad_row])


async def _try_lock(engine: AsyncEngine) -> bool:
    async with engine.connect() as other:
        acquired = await other.scalar(
            text("SELECT pg_try_advisory_xact_lock(CAST(:key AS bigint))"),
            {"key": SEED_ADVISORY_LOCK_KEY},
        )
        await other.rollback()
    return bool(acquired)


@pytest.mark.db
async def test_advisory_lock_blocks_parallel_run(
    seed_conn: AsyncConnection, async_engine: AsyncEngine
) -> None:
    assert await _try_lock(async_engine) is True
    await common.acquire_lock(seed_conn)
    assert await _try_lock(async_engine) is False
