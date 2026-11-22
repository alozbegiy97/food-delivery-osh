"""Seed mode `demo` (DEC-136, DEC-137, DEC-138, DEC-139).

Runs only on the isolated `db-test`: every test works inside a transaction
that is always rolled back (`seed_conn`), so nothing persists. Error tests
compare full snapshots of all 15 watched tables before and after the error.
"""

import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Table, delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.base import Base
from app.modules.catalog.models import (
    Category,
    CategoryTranslation,
    Modifier,
    ModifierGroupTranslation,
    ModifierTranslation,
    Product,
    ProductTranslation,
    ProductVariant,
    ProductVariantTranslation,
)
from app.modules.delivery.models import DeliveryZone
from app.modules.payments.models import PaymentMethod
from app.modules.restaurant.models import RestaurantSettings
from app.modules.users.models import Role
from app.seeds import common, demo
from app.seeds import demo_data as data
from app.seeds.base import seed_base
from app.seeds.common import SEED_ADVISORY_LOCK_KEY, SeedError
from app.seeds.demo import seed_demo

pytestmark = pytest.mark.db

DEMO_TABLES = [
    "delivery_zones",
    "categories",
    "category_translations",
    "modifier_groups",
    "modifier_group_translations",
    "modifiers",
    "modifier_translations",
    "products",
    "product_translations",
    "product_modifier_groups",
    "product_variants",
    "product_variant_translations",
    "variant_modifier_prices",
]
SNAPSHOT_TABLES = [*DEMO_TABLES, "users", "user_roles"]
BASE_TABLES = ["roles", "payment_methods", "restaurant_settings", "restaurant_working_hours"]

FIRST_RUN_COUNTS = {
    "delivery_zones": (1, 0),
    "categories": (8, 0),
    "category_translations": (24, 0),
    "modifier_groups": (4, 0),
    "modifier_group_translations": (12, 0),
    "modifiers": (10, 0),
    "modifier_translations": (30, 0),
    "products": (21, 0),
    "product_translations": (63, 0),
    "product_modifier_groups": (11, 0),
    "product_variants": (30, 0),
    "product_variant_translations": (90, 0),
    "variant_modifier_prices": (9, 0),
}

APPROVED_WKT = data.DEMO_ZONE.boundary_wkt
OVERLAPPING_WKT = (
    "MULTIPOLYGON(((72.80 40.53, 72.90 40.53, 72.90 40.60, 72.80 40.60, 72.80 40.53)))"
)
TOUCHING_WKT = "MULTIPOLYGON(((72.86 40.49, 72.90 40.49, 72.90 40.57, 72.86 40.57, 72.86 40.49)))"
DISTANT_WKT = "MULTIPOLYGON(((74.50 42.80, 74.60 42.80, 74.60 42.90, 74.50 42.90, 74.50 42.80)))"


# --- Helpers ------------------------------------------------------------------


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


async def _snapshot(conn: AsyncConnection) -> dict[str, list[tuple[Any, ...]]]:
    """Every column of every row of the 15 watched tables, ordered by PK."""
    snapshot = {}
    for name in SNAPSHOT_TABLES:
        table = _table(name)
        columns = [
            func.ST_AsEWKT(column).label(column.name) if column.name == "boundary" else column
            for column in table.columns
        ]
        query = select(*columns).order_by(*table.primary_key.columns)
        snapshot[name] = [tuple(row) for row in await conn.execute(query)]
    return snapshot


async def _pk_sets(conn: AsyncConnection) -> dict[str, set[tuple[Any, ...]]]:
    result = {}
    for name in DEMO_TABLES:
        table = _table(name)
        rows = await conn.execute(select(*table.primary_key.columns))
        result[name] = {tuple(row) for row in rows}
    return result


async def _require_clean(conn: AsyncConnection) -> None:
    for name in [*DEMO_TABLES, *BASE_TABLES]:
        count = await conn.scalar(select(func.count()).select_from(_table(name)))
        if count:
            pytest.fail(f"db-test is expected to have an empty {name} table, found {count}")


async def _add_zone(conn: AsyncConnection, wkt: str, *, active: bool = True) -> uuid.UUID:
    zone_id = uuid.uuid4()
    await conn.execute(
        insert(DeliveryZone).values(
            id=zone_id,
            name="Чужая зона",
            delivery_fee=Decimal("50.00"),
            is_active=active,
            boundary=func.ST_GeomFromText(wkt, 4326),
        )
    )
    return zone_id


async def _add_category(conn: AsyncConnection, slug: str) -> uuid.UUID:
    category_id = uuid.uuid4()
    await conn.execute(insert(Category).values(id=category_id, slug=slug))
    return category_id


async def _expect_error_without_changes(conn: AsyncConnection, message: str) -> str:
    before = await _snapshot(conn)
    with pytest.raises(SeedError, match=message) as error:
        await seed_demo(conn)
    assert await _snapshot(conn) == before
    return str(error.value)


async def _base_and_demo(conn: AsyncConnection) -> None:
    await _require_clean(conn)
    await seed_base(conn)
    await seed_demo(conn)


# --- First and repeated runs -----------------------------------------------------


async def test_first_run_creates_everything(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)

    report = await seed_demo(seed_conn)

    assert report.counts == FIRST_RUN_COUNTS
    for name, (created, _) in FIRST_RUN_COUNTS.items():
        assert await seed_conn.scalar(select(func.count()).select_from(_table(name))) == created


async def test_zone_geometry_and_values(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    zones = _table("delivery_zones")
    row = (
        await seed_conn.execute(
            select(
                zones.c.name,
                zones.c.description,
                zones.c.delivery_fee,
                zones.c.min_order_amount,
                zones.c.is_active,
                func.ST_Equals(zones.c.boundary, func.ST_GeomFromText(APPROVED_WKT, 4326)),
                func.ST_IsValid(zones.c.boundary),
                func.ST_SRID(zones.c.boundary),
                func.GeometryType(zones.c.boundary),
            ).where(zones.c.id == data.zone_id("osh"))
        )
    ).one()
    assert tuple(row) == (
        "Демо-зона доставки — Ош",
        "Демонстрационная зона доставки для тестирования каталога. "
        "Не является утверждённой рестораном зоной обслуживания.",
        Decimal("100.00"),
        Decimal("500.00"),
        True,
        True,
        True,
        4326,
        "MULTIPOLYGON",
    )


async def test_ids_are_seed_uuids(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    expected = {
        "categories": {data.category_id(c.slug) for c in data.CATEGORIES},
        "products": {data.product_id(p.code) for p in data.PRODUCTS},
        "product_variants": {
            data.variant_id(p.code, v.code) for p in data.PRODUCTS for v in p.variants
        },
        "modifier_groups": {data.group_id(g.code) for g in data.MODIFIER_GROUPS},
        "modifiers": {
            data.modifier_id(g.code, m.code) for g in data.MODIFIER_GROUPS for m in g.modifiers
        },
        "category_translations": {row["id"] for row in data.category_translation_rows()},
        "product_variant_translations": {row["id"] for row in data.variant_translation_rows()},
    }
    for name, ids in expected.items():
        table = _table(name)
        assert set((await seed_conn.scalars(select(table.c.id))).all()) == ids, name


async def test_second_run_creates_nothing(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    before = await _snapshot(seed_conn)

    report = await seed_demo(seed_conn)

    assert report.counts == {name: (0, created) for name, (created, _) in FIRST_RUN_COUNTS.items()}
    assert await _snapshot(seed_conn) == before


# --- Existing records, restore, soft delete --------------------------------------


async def test_admin_changes_are_kept(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    variant_id = data.variant_id("pizza-margherita", "30")
    product_id = data.product_id("plov")
    pizza_id = data.category_id("pizza")
    await seed_conn.execute(
        update(ProductVariant)
        .where(ProductVariant.id == variant_id)
        .values(price=Decimal("999.00"))
    )
    await seed_conn.execute(
        update(Product).where(Product.id == product_id).values(is_available=False)
    )
    await seed_conn.execute(
        update(CategoryTranslation)
        .where(
            CategoryTranslation.category_id == pizza_id, CategoryTranslation.language_code == "ru"
        )
        .values(name="Пицца от шефа")
    )
    await seed_conn.execute(
        update(Category).where(Category.id == pizza_id).values(slug="pizza-chef")
    )
    await seed_conn.execute(
        update(DeliveryZone).where(DeliveryZone.id == data.zone_id("osh")).values(is_active=False)
    )
    before = await _snapshot(seed_conn)

    report = await seed_demo(seed_conn)

    assert all(created == 0 for created, _ in report.counts.values())
    assert await _snapshot(seed_conn) == before


async def test_deleted_records_are_restored(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    expected = await _pk_sets(seed_conn)
    await seed_conn.execute(
        delete(Product).where(Product.id == data.product_id("pizza-margherita"))
    )
    await seed_conn.execute(
        delete(Modifier).where(Modifier.id == data.modifier_id("pizza-extras", "jalapeno"))
    )
    await seed_conn.execute(
        delete(CategoryTranslation).where(
            CategoryTranslation.category_id == data.category_id("drinks"),
            CategoryTranslation.language_code == "uz",
        )
    )
    assert await _pk_sets(seed_conn) != expected

    report = await seed_demo(seed_conn)

    assert await _pk_sets(seed_conn) == expected
    assert report.created("products") == 1
    assert report.created("modifiers") == 1
    assert report.created("variant_modifier_prices") == 5  # 3 margherita-40 + 2 jalapeno


async def test_soft_deleted_product_children_restored(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    product_id = data.product_id("manty")
    deleted_at = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    await seed_conn.execute(
        update(Product).where(Product.id == product_id).values(deleted_at=deleted_at)
    )
    await seed_conn.execute(
        delete(ProductVariant).where(ProductVariant.id == data.variant_id("manty", "10pcs"))
    )

    report = await seed_demo(seed_conn)

    assert report.counts["products"] == (0, 21)
    assert report.created("product_variants") == 1
    assert report.created("product_variant_translations") == 3
    variant = await seed_conn.scalar(
        select(ProductVariant.sku).where(ProductVariant.id == data.variant_id("manty", "10pcs"))
    )
    assert variant == "DEMO-MANTY-10PCS"
    assert await seed_conn.scalar(select(Product.deleted_at).where(Product.id == product_id)) == (
        deleted_at
    )


# --- Error kind 1: base ------------------------------------------------------------


async def test_demo_requires_base(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    message = await _expect_error_without_changes(seed_conn, "требует выполненного base")
    assert "python -m app.seeds base" in message
    assert "роль customer" in message
    assert "способ оплаты cash" in message
    assert "restaurant_settings" in message


@pytest.mark.parametrize(
    ("model", "condition", "expected"),
    [
        (Role, lambda: Role.name == "cook", "роль cook"),
        (PaymentMethod, lambda: PaymentMethod.code == "mock_card", "способ оплаты mock_card"),
        (RestaurantSettings, lambda: RestaurantSettings.id == 1, "restaurant_settings"),
    ],
)
async def test_missing_base_record(
    seed_conn: AsyncConnection, model: type[Base], condition: Any, expected: str
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    await seed_conn.execute(delete(model).where(condition()))

    message = await _expect_error_without_changes(seed_conn, "требует выполненного base")

    assert expected in message


# --- Error kind 2: zone overlap (DEC-139) ----------------------------------------


async def test_rerun_without_foreign_overlap_passes(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    await _add_zone(seed_conn, DISTANT_WKT)
    report = await seed_demo(seed_conn)
    assert report.created("delivery_zones") == 0


async def test_existing_demo_zone_does_not_conflict_with_itself(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    assert await demo.demo_zone_state(seed_conn) is True
    assert await demo.find_overlapping_zones(seed_conn) == []
    report = await seed_demo(seed_conn)
    assert report.counts["delivery_zones"] == (0, 1)


async def test_new_foreign_overlap_after_creation_fails(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    foreign = await _add_zone(seed_conn, OVERLAPPING_WKT)
    await seed_conn.execute(
        delete(CategoryTranslation).where(
            CategoryTranslation.id == data.category_translation_rows()[0]["id"]
        )
    )

    message = await _expect_error_without_changes(seed_conn, "пересекается по площади")

    assert str(foreign) in message


async def test_foreign_overlap_before_first_run_fails(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    foreign = await _add_zone(seed_conn, OVERLAPPING_WKT)

    message = await _expect_error_without_changes(seed_conn, "пересекается по площади")

    assert str(foreign) in message
    assert await demo.demo_zone_state(seed_conn) is None


@pytest.mark.parametrize(
    ("wkt", "active"),
    [(OVERLAPPING_WKT, False), (TOUCHING_WKT, True), (DISTANT_WKT, True)],
    ids=["inactive-overlapping", "touching", "distant"],
)
async def test_zone_that_is_not_an_overlap(
    seed_conn: AsyncConnection, wkt: str, active: bool
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    await _add_zone(seed_conn, wkt, active=active)

    report = await seed_demo(seed_conn)

    assert report.counts["delivery_zones"] == (1, 0)


async def test_inactive_demo_zone_skips_overlap_check(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    await seed_conn.execute(
        update(DeliveryZone).where(DeliveryZone.id == data.zone_id("osh")).values(is_active=False)
    )
    await _add_zone(seed_conn, OVERLAPPING_WKT)

    report = await seed_demo(seed_conn)

    assert report.counts["delivery_zones"] == (0, 1)
    assert await demo.demo_zone_state(seed_conn) is False


async def test_overlap_uses_approved_geometry(seed_conn: AsyncConnection) -> None:
    """DEC-139 a1: the stored boundary of the demo zone is not used."""
    await _base_and_demo(seed_conn)
    await seed_conn.execute(
        update(DeliveryZone)
        .where(DeliveryZone.id == data.zone_id("osh"))
        .values(boundary=func.ST_GeomFromText(DISTANT_WKT, 4326))
    )
    # Overlaps only the moved (stored) boundary, not the approved rectangle.
    await _add_zone(
        seed_conn,
        "MULTIPOLYGON(((74.55 42.85, 74.70 42.85, 74.70 42.95, 74.55 42.95, 74.55 42.85)))",
    )
    await seed_demo(seed_conn)

    # Overlaps the approved rectangle, although the stored boundary is far away.
    foreign = await _add_zone(seed_conn, OVERLAPPING_WKT)
    message = await _expect_error_without_changes(seed_conn, "пересекается по площади")
    assert str(foreign) in message


# --- Error kind 3: natural keys and translation UUIDs ----------------------------


async def test_natural_key_conflicts_listed_together(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    foreign_category = await _add_category(seed_conn, "pizza")
    foreign_product = uuid.uuid4()
    await seed_conn.execute(
        insert(Product).values(id=foreign_product, category_id=foreign_category, slug="demo-plov")
    )
    foreign_variant = uuid.uuid4()
    await seed_conn.execute(
        insert(ProductVariant).values(
            id=foreign_variant, product_id=foreign_product, sku="DEMO-PLOV-STD", price=1
        )
    )

    message = await _expect_error_without_changes(
        seed_conn, r"найдены конфликты demo-записей \(3\)"
    )

    assert f"categories: demo.category.pizza: slug = 'pizza' занят записью {foreign_category}" in (
        message
    )
    assert f"products: demo.product.plov: slug = 'demo-plov' занят записью {foreign_product}" in (
        message
    )
    assert (
        "product_variants: demo.variant.plov.std: sku = 'DEMO-PLOV-STD' "
        f"занят записью {foreign_variant}"
    ) in message


async def test_own_record_with_changed_key_is_not_a_conflict(seed_conn: AsyncConnection) -> None:
    await _base_and_demo(seed_conn)
    await seed_conn.execute(
        update(ProductVariant)
        .where(ProductVariant.id == data.variant_id("plov", "std"))
        .values(sku="ADMIN-PLOV")
    )
    await seed_conn.execute(
        update(Product).where(Product.id == data.product_id("plov")).values(slug="admin-plov")
    )

    report = await seed_demo(seed_conn)

    assert all(created == 0 for created, _ in report.counts.values())


async def test_existing_translation_pair_with_other_id_is_skipped(
    seed_conn: AsyncConnection,
) -> None:
    await _base_and_demo(seed_conn)
    pizza = data.category_id("pizza")
    pair = (CategoryTranslation.category_id == pizza, CategoryTranslation.language_code == "ru")
    await seed_conn.execute(delete(CategoryTranslation).where(*pair))
    other_id = uuid.uuid4()
    await seed_conn.execute(
        insert(CategoryTranslation).values(
            id=other_id, category_id=pizza, language_code="ru", name="Пицца (админ)"
        )
    )

    report = await seed_demo(seed_conn)

    assert report.counts["category_translations"] == (0, 24)
    assert await seed_conn.scalar(select(CategoryTranslation.id).where(*pair)) == other_id


async def test_translation_uuid_taken_by_other_pair_is_conflict(
    seed_conn: AsyncConnection,
) -> None:
    await _base_and_demo(seed_conn)
    expected_id = data.translation_id("category", "pizza", data.Language.RU)
    await seed_conn.execute(
        delete(CategoryTranslation).where(CategoryTranslation.id == expected_id)
    )
    foreign_category = await _add_category(seed_conn, "foreign-category")
    await seed_conn.execute(
        insert(CategoryTranslation).values(
            id=expected_id, category_id=foreign_category, language_code="ru", name="Чужая"
        )
    )

    message = await _expect_error_without_changes(
        seed_conn, r"найдены конфликты demo-записей \(1\)"
    )

    assert "category_translations: demo.translation.category.pizza.ru" in message
    assert str(foreign_category) in message


# --- Order of error kinds ------------------------------------------------------------


async def test_base_error_comes_before_overlap(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await _add_zone(seed_conn, OVERLAPPING_WKT)

    message = await _expect_error_without_changes(seed_conn, "требует выполненного base")

    assert "пересекается" not in message


async def test_overlap_error_comes_before_conflicts(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    await _add_zone(seed_conn, OVERLAPPING_WKT)
    await _add_category(seed_conn, "pizza")

    message = await _expect_error_without_changes(seed_conn, "пересекается по площади")

    assert "конфликты" not in message


# --- Races after the preliminary check -------------------------------------------------


async def _no_conflicts(_conn: AsyncConnection) -> list[str]:
    return []


async def _race_rolls_back(conn: AsyncConnection, constraint: str) -> None:
    before = await _snapshot(conn)
    with pytest.raises(SeedError, match=constraint):
        async with conn.begin_nested():
            await seed_demo(conn)
    assert await _snapshot(conn) == before


async def test_race_on_slug_rolls_back(
    seed_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    await _add_category(seed_conn, "pizza")  # appears "after" the (skipped) check
    monkeypatch.setattr(demo, "collect_conflicts", _no_conflicts)

    await _race_rolls_back(seed_conn, "uq_categories_slug")


async def test_race_on_translation_uuid_rolls_back(
    seed_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _base_and_demo(seed_conn)
    expected_id = data.translation_id("category", "pizza", data.Language.RU)
    await seed_conn.execute(
        delete(CategoryTranslation).where(CategoryTranslation.id == expected_id)
    )
    foreign_category = await _add_category(seed_conn, "foreign-category")
    await seed_conn.execute(
        insert(CategoryTranslation).values(
            id=expected_id, category_id=foreign_category, language_code="ru", name="Чужая"
        )
    )
    monkeypatch.setattr(demo, "collect_conflicts", _no_conflicts)

    await _race_rolls_back(seed_conn, "pk_category_translations")


async def _add_foreign_product(conn: AsyncConnection, slug: str) -> uuid.UUID:
    category = await _add_category(conn, "foreign-category")
    product = uuid.uuid4()
    await conn.execute(insert(Product).values(id=product, category_id=category, slug=slug))
    return product


async def test_race_on_product_slug_rolls_back(
    seed_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    await _add_foreign_product(seed_conn, "demo-plov")  # appears "after" the check
    monkeypatch.setattr(demo, "collect_conflicts", _no_conflicts)

    await _race_rolls_back(seed_conn, "uq_products_slug")


async def test_race_on_variant_sku_rolls_back(
    seed_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    product = await _add_foreign_product(seed_conn, "foreign-product")
    await seed_conn.execute(
        insert(ProductVariant).values(product_id=product, sku="DEMO-PLOV-STD", price=1)
    )
    monkeypatch.setattr(demo, "collect_conflicts", _no_conflicts)

    await _race_rolls_back(seed_conn, "uq_product_variants_sku")


# --- Translation rules for all five tables (DEC-137, DEC-138 rule (b)) ----------------

TRANSLATION_CASES = [
    pytest.param(
        CategoryTranslation,
        "category_id",
        "category",
        "pizza",
        data.category_id("pizza"),
        24,
        id="category_translations",
    ),
    pytest.param(
        ProductTranslation,
        "product_id",
        "product",
        "plov",
        data.product_id("plov"),
        63,
        id="product_translations",
    ),
    pytest.param(
        ProductVariantTranslation,
        "variant_id",
        "variant",
        "manty.10pcs",
        data.variant_id("manty", "10pcs"),
        90,
        id="product_variant_translations",
    ),
    pytest.param(
        ModifierGroupTranslation,
        "group_id",
        "group",
        "pizza-dough",
        data.group_id("pizza-dough"),
        12,
        id="modifier_group_translations",
    ),
    pytest.param(
        ModifierTranslation,
        "modifier_id",
        "modifier",
        "pizza-extras.cheese",
        data.modifier_id("pizza-extras", "cheese"),
        30,
        id="modifier_translations",
    ),
]


@pytest.mark.parametrize(
    ("model", "parent_column", "parent_type", "parent_code", "parent_id", "total"),
    TRANSLATION_CASES,
)
async def test_translation_pair_with_other_id_is_skipped_all_tables(
    seed_conn: AsyncConnection,
    model: type[Base],
    parent_column: str,
    parent_type: str,
    parent_code: str,
    parent_id: uuid.UUID,
    total: int,
) -> None:
    """Rule (b) 1: an existing pair is skipped, its own UUID is not compared."""
    await _base_and_demo(seed_conn)
    table = common.table_of(model)
    expected_id = data.translation_id(parent_type, parent_code, data.Language.RU)
    await seed_conn.execute(delete(table).where(table.c.id == expected_id))
    other_id = uuid.uuid4()
    await seed_conn.execute(
        insert(table).values(
            id=other_id, **{parent_column: parent_id}, language_code="ru", name="Изменено"
        )
    )
    before = await _snapshot(seed_conn)

    report = await seed_demo(seed_conn)

    assert report.counts[table.name] == (0, total)
    assert await _snapshot(seed_conn) == before  # the pair keeps its other id and name


@pytest.mark.parametrize(
    ("model", "parent_column", "parent_type", "parent_code", "parent_id", "total"),
    TRANSLATION_CASES,
)
async def test_translation_uuid_taken_by_other_pair_all_tables(
    seed_conn: AsyncConnection,
    model: type[Base],
    parent_column: str,
    parent_type: str,
    parent_code: str,
    parent_id: uuid.UUID,
    total: int,
) -> None:
    """Rule (b) 2: the expected pair is missing and its UUIDv5 is taken by another pair."""
    await _base_and_demo(seed_conn)
    table = common.table_of(model)
    ru_id = data.translation_id(parent_type, parent_code, data.Language.RU)
    ky_id = data.translation_id(parent_type, parent_code, data.Language.KY)
    await seed_conn.execute(delete(table).where(table.c.id.in_([ru_id, ky_id])))
    # The expected `ru` UUID now holds the pair (parent, ky); the pair (parent, ru) is missing.
    await seed_conn.execute(
        insert(table).values(
            id=ru_id, **{parent_column: parent_id}, language_code="ky", name="Чужая пара"
        )
    )

    message = await _expect_error_without_changes(
        seed_conn, r"найдены конфликты demo-записей \(1\)"
    )

    code = data.translation_code(parent_type, parent_code, data.Language.RU)
    assert f"{table.name}: {code}: UUIDv5 {ru_id} занят парой" in message
    assert f"{parent_column} = {parent_id}, language_code = ky" in message


# --- Combined conflicts of kind 3 ----------------------------------------------------------


async def test_natural_key_and_translation_conflicts_listed_together(
    seed_conn: AsyncConnection,
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    foreign_category = await _add_category(seed_conn, "pizza")
    foreign_product = await _add_foreign_product(seed_conn, "foreign-product")
    taken_id = data.translation_id("product", "plov", data.Language.RU)
    await seed_conn.execute(
        insert(ProductTranslation).values(
            id=taken_id, product_id=foreign_product, language_code="ru", name="Чужой товар"
        )
    )

    message = await _expect_error_without_changes(
        seed_conn, r"найдены конфликты demo-записей \(2\)"
    )

    assert f"categories: demo.category.pizza: slug = 'pizza' занят записью {foreign_category}" in (
        message
    )
    assert (
        f"product_translations: demo.translation.product.plov.ru: UUIDv5 {taken_id} занят парой "
        f"(product_id = {foreign_product}, language_code = ru)"
    ) in message


# --- Other guarantees ------------------------------------------------------------------


async def test_wrong_revision_stops_before_any_change(
    seed_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    monkeypatch.setattr(common, "get_migration_heads", lambda: ["0008_a", "0008_b"])

    await _expect_error_without_changes(seed_conn, "ровно одна head-ревизия")


async def test_no_users_created(seed_conn: AsyncConnection) -> None:
    await _require_clean(seed_conn)
    await seed_base(seed_conn)
    before = await _snapshot(seed_conn)

    await seed_demo(seed_conn)
    await seed_demo(seed_conn)

    after = await _snapshot(seed_conn)
    assert after["users"] == before["users"]
    assert after["user_roles"] == before["user_roles"]


async def test_demo_holds_seed_advisory_lock(
    seed_conn: AsyncConnection, async_engine: AsyncEngine
) -> None:
    await _base_and_demo(seed_conn)
    async with async_engine.connect() as other:
        acquired = await other.scalar(
            text("SELECT pg_try_advisory_xact_lock(CAST(:key AS bigint))"),
            {"key": SEED_ADVISORY_LOCK_KEY},
        )
        await other.rollback()
    assert acquired is False


def test_demo_module_has_no_transaction_control_or_updates() -> None:
    source = inspect.getsource(demo)
    for forbidden in ("commit(", "rollback(", "begin(", "begin_nested(", "update(", "delete("):
        assert forbidden not in source, forbidden
