"""Seed mode `base` (DEC-117, DEC-136, DEC-137).

Runs only on the isolated `db-test`; every test works inside a transaction
that is always rolled back (`seed_conn`), so nothing persists.
"""

from datetime import time
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.base import Base
from app.modules.payments.models import PaymentMethod
from app.modules.restaurant.models import RestaurantSettings, RestaurantWorkingHours
from app.modules.users.models import Role, User, UserRole
from app.seeds import common
from app.seeds.base import seed_base
from app.seeds.common import SeedError

pytestmark = pytest.mark.db

BASE_MODELS: list[type[Base]] = [Role, PaymentMethod, RestaurantSettings, RestaurantWorkingHours]
WATCHED_MODELS: list[type[Base]] = [*BASE_MODELS, User, UserRole]


async def _count(conn: AsyncConnection, model: type[Base]) -> int:
    return int(await conn.scalar(select(func.count()).select_from(model)) or 0)


async def _counts(conn: AsyncConnection) -> dict[str, int]:
    return {model.__tablename__: await _count(conn, model) for model in WATCHED_MODELS}


async def _require_empty_base(conn: AsyncConnection) -> None:
    counts = await _counts(conn)
    if any(counts.values()):
        pytest.fail(f"db-test is expected to have empty base/user tables, found {counts}")


async def _rows(conn: AsyncConnection, model: type[Base], *columns: str) -> list[tuple[Any, ...]]:
    table = common.table_of(model)
    result = await conn.execute(select(*(table.c[name] for name in columns)).order_by(*columns))
    return [tuple(row) for row in result]


async def test_first_run_creates_all_base_records(seed_conn: AsyncConnection) -> None:
    await _require_empty_base(seed_conn)

    report = await seed_base(seed_conn)

    assert report.counts == {
        "roles": (4, 0),
        "payment_methods": (2, 0),
        "restaurant_settings": (1, 0),
        "restaurant_working_hours": (7, 0),
    }
    assert await _rows(seed_conn, Role, "name", "description") == [
        ("admin", None),
        ("cook", None),
        ("courier", None),
        ("customer", None),
    ]
    assert await _rows(seed_conn, PaymentMethod, "sort_order", "code", "is_active") == [
        (0, "cash", True),
        (1, "mock_card", True),
    ]
    settings = common.table_of(RestaurantSettings)
    row = (await seed_conn.execute(select(settings))).mappings().one()
    assert row["id"] == 1
    assert row["restaurant_name"] == "Demo Restaurant — Osh"
    assert row["phone"] == "+996000000000"
    assert row["address"] == "Демонстрационный адрес, г. Ош"
    assert row["latitude"] is None
    assert row["longitude"] is None
    assert row["min_order_amount"] == Decimal("300.00")
    assert row["delivery_enabled"] is True
    assert row["pickup_enabled"] is True
    assert row["timezone"] == "Asia/Bishkek"
    assert await _rows(
        seed_conn, RestaurantWorkingHours, "weekday", "opens_at", "closes_at", "is_closed"
    ) == [(weekday, time(10, 0), time(23, 0), False) for weekday in range(7)]


async def test_second_run_creates_no_duplicates(seed_conn: AsyncConnection) -> None:
    await _require_empty_base(seed_conn)
    await seed_base(seed_conn)
    counts_after_first = await _counts(seed_conn)

    report = await seed_base(seed_conn)

    assert report.counts == {
        "roles": (0, 4),
        "payment_methods": (0, 2),
        "restaurant_settings": (0, 1),
        "restaurant_working_hours": (0, 7),
    }
    assert await _counts(seed_conn) == counts_after_first


async def test_existing_records_and_admin_changes_are_kept(seed_conn: AsyncConnection) -> None:
    await _require_empty_base(seed_conn)
    # A record that existed before the first run, with its own value.
    await seed_conn.execute(insert(Role).values(name="admin", description="Главный"))

    report = await seed_base(seed_conn)
    assert report.counts["roles"] == (3, 1)

    # Admin edits after seeding.
    await seed_conn.execute(
        update(PaymentMethod)
        .where(PaymentMethod.code == "mock_card")
        .values(is_active=False, sort_order=5)
    )
    await seed_conn.execute(
        update(RestaurantSettings).values(
            restaurant_name="Изменено администратором", min_order_amount=Decimal("450.00")
        )
    )
    await seed_conn.execute(
        update(RestaurantWorkingHours)
        .where(RestaurantWorkingHours.weekday == 6)
        .values(opens_at=time(12, 0), closes_at=time(20, 0), is_closed=True)
    )

    report = await seed_base(seed_conn)

    assert report.created("roles") == 0
    assert report.created("payment_methods") == 0
    assert report.created("restaurant_settings") == 0
    assert report.created("restaurant_working_hours") == 0
    assert ("admin", "Главный") in await _rows(seed_conn, Role, "name", "description")
    assert (5, "mock_card", False) in await _rows(
        seed_conn, PaymentMethod, "sort_order", "code", "is_active"
    )
    assert await _rows(seed_conn, RestaurantSettings, "restaurant_name", "min_order_amount") == [
        ("Изменено администратором", Decimal("450.00"))
    ]
    assert (6, time(12, 0), time(20, 0), True) in await _rows(
        seed_conn, RestaurantWorkingHours, "weekday", "opens_at", "closes_at", "is_closed"
    )


async def test_missing_records_are_restored(seed_conn: AsyncConnection) -> None:
    await _require_empty_base(seed_conn)
    await seed_base(seed_conn)
    await seed_conn.execute(delete(Role).where(Role.name == "cook"))
    await seed_conn.execute(delete(PaymentMethod).where(PaymentMethod.code == "mock_card"))
    await seed_conn.execute(delete(RestaurantSettings))
    await seed_conn.execute(
        delete(RestaurantWorkingHours).where(RestaurantWorkingHours.weekday == 3)
    )

    report = await seed_base(seed_conn)

    assert report.counts == {
        "roles": (1, 3),
        "payment_methods": (1, 1),
        "restaurant_settings": (1, 0),
        "restaurant_working_hours": (1, 6),
    }
    assert await _count(seed_conn, Role) == 4
    assert await _count(seed_conn, PaymentMethod) == 2
    assert await _count(seed_conn, RestaurantSettings) == 1
    weekdays = await _rows(seed_conn, RestaurantWorkingHours, "weekday")
    assert [weekday for (weekday,) in weekdays] == list(range(7))


async def test_no_users_are_created(seed_conn: AsyncConnection) -> None:
    before = (await _count(seed_conn, User), await _count(seed_conn, UserRole))

    await seed_base(seed_conn)
    await seed_base(seed_conn)

    assert (await _count(seed_conn, User), await _count(seed_conn, UserRole)) == before


@pytest.mark.parametrize(
    ("heads", "versions", "message"),
    [
        (["0008_notifications"], ["0007_payments_deliveries"], "не равна head"),
        (["0008_notifications"], [], "ровно одна строка, найдено 0"),
        (["0008_notifications"], ["0007_x", "0008_notifications"], "ровно одна строка"),
        (["0008_notifications"], None, "нет таблицы alembic_version"),
        (["0008_a", "0008_b"], ["0008_a"], "ровно одна head-ревизия"),
    ],
)
async def test_wrong_revision_stops_before_any_change(
    seed_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    heads: list[str],
    versions: list[str] | None,
    message: str,
) -> None:
    """The revision state is simulated: the real alembic_version is not touched."""

    async def fake_versions(_conn: AsyncConnection) -> list[str] | None:
        return versions

    monkeypatch.setattr(common, "get_migration_heads", lambda: heads)
    monkeypatch.setattr(common, "read_alembic_versions", fake_versions)
    before = await _counts(seed_conn)

    with pytest.raises(SeedError, match=message):
        await seed_base(seed_conn)

    assert await _counts(seed_conn) == before
