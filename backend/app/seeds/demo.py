"""Seed mode `demo`: demo delivery zone and catalog (DEC-136…DEC-139).

Order inside the caller's transaction (this module never commits, rolls
back or opens transactions/savepoints):

1. `prepare_seed`: advisory lock, strict Alembic revision check;
2. `base` precondition (error kind 1, DEC-139);
3. overlap of the approved demo geometry with other active zones, unless
   the existing demo zone is inactive (error kind 2, DEC-139);
4. natural-key conflicts and translation UUID conflicts, one common list
   (error kind 3, DEC-137, DEC-138);
5. inserts of missing rows only, parents before children.

Steps 1-4 only read; any SeedError there happens before the first insert.
Existing rows are never updated or deleted: `is_active`, `is_available`,
`deleted_at` and all other data of existing demo records stay as they
are. Users and user roles are never touched.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.base import Base
from app.modules.catalog.models import (
    Category,
    CategoryTranslation,
    Modifier,
    ModifierGroup,
    ModifierGroupTranslation,
    ModifierTranslation,
    Product,
    ProductModifierGroup,
    ProductTranslation,
    ProductVariant,
    ProductVariantTranslation,
    VariantModifierPrice,
)
from app.modules.delivery.models import DeliveryZone
from app.modules.payments.enums import PaymentMethodCode
from app.modules.payments.models import PaymentMethod
from app.modules.restaurant.models import RESTAURANT_SETTINGS_ID, RestaurantSettings
from app.modules.users.enums import RoleName
from app.modules.users.models import Role
from app.seeds import demo_data as data
from app.seeds.common import SeedError, SeedReport, insert_missing, prepare_seed, table_of

# --- Error kind 1: base precondition ----------------------------------------


async def check_base_ready(conn: AsyncConnection) -> None:
    """`demo` requires `base`: settings row id=1, all 4 roles, both methods."""
    missing: list[str] = []

    settings = table_of(RestaurantSettings)
    settings_id = await conn.scalar(
        select(settings.c.id).where(settings.c.id == RESTAURANT_SETTINGS_ID)
    )
    if settings_id is None:
        missing.append(f"строка restaurant_settings с id = {RESTAURANT_SETTINGS_ID}")

    roles = table_of(Role)
    role_names = [role.value for role in RoleName]
    found_roles = set(
        (await conn.scalars(select(roles.c.name).where(roles.c.name.in_(role_names)))).all()
    )
    missing += [f"роль {name}" for name in role_names if name not in found_roles]

    methods = table_of(PaymentMethod)
    codes = [code.value for code in PaymentMethodCode]
    found_codes = set(
        (await conn.scalars(select(methods.c.code).where(methods.c.code.in_(codes)))).all()
    )
    missing += [f"способ оплаты {code}" for code in codes if code not in found_codes]

    if missing:
        raise SeedError(
            "режим demo требует выполненного base; отсутствует: "
            + "; ".join(missing)
            + ". Сначала выполните `python -m app.seeds base`."
        )


# --- Error kind 2: zone overlap (DEC-139) ------------------------------------


def _demo_zone_id() -> UUID:
    return data.zone_id(data.DEMO_ZONE.code)


def _approved_boundary() -> Any:
    """The approved DEMO_ZONE geometry; WKT and SRID are bound parameters."""
    return func.ST_GeomFromText(data.DEMO_ZONE.boundary_wkt, data.DEMO_ZONE.srid)


async def demo_zone_state(conn: AsyncConnection) -> bool | None:
    """None: demo zone absent; True: exists and active; False: exists, inactive.

    Only `is_active` is read; the stored `boundary` is not (DEC-139).
    """
    table = table_of(DeliveryZone)
    return await conn.scalar(select(table.c.is_active).where(table.c.id == _demo_zone_id()))


async def find_overlapping_zones(conn: AsyncConnection) -> list[UUID]:
    """Other active zones whose interior intersects the approved geometry."""
    table = table_of(DeliveryZone)
    query = (
        select(table.c.id)
        .where(
            table.c.is_active.is_(True),
            table.c.boundary.is_not(None),
            table.c.id != _demo_zone_id(),
            func.ST_Relate(table.c.boundary, _approved_boundary(), "T********"),
        )
        .order_by(table.c.id)
    )
    return list((await conn.scalars(query)).all())


async def check_zone_overlap(conn: AsyncConnection) -> None:
    if await demo_zone_state(conn) is False:
        return  # existing inactive demo zone: check skipped (DEC-139)
    overlapping = await find_overlapping_zones(conn)
    if overlapping:
        ids = ", ".join(str(zone) for zone in overlapping)
        raise SeedError(
            "граница демо-зоны пересекается по площади с активными зонами доставки: "
            f"{ids}. Демо-данные не созданы."
        )


# --- Error kind 3: natural keys and translation UUIDs ----------------------


async def _natural_key_conflicts(
    conn: AsyncConnection,
    model: type[Base],
    key: str,
    expected: list[tuple[str, UUID, str]],
) -> list[str]:
    """Expected (code, id, key value); conflict = key held by another id (DEC-137)."""
    table = table_of(model)
    ids = [record_id for _, record_id, _ in expected]
    keys = [value for _, _, value in expected]
    rows = (
        await conn.execute(
            select(table.c.id, table.c[key]).where(or_(table.c.id.in_(ids), table.c[key].in_(keys)))
        )
    ).all()
    existing_ids = {row[0] for row in rows}
    key_owner = {row[1]: row[0] for row in rows}
    conflicts = []
    for code, record_id, value in expected:
        if record_id in existing_ids:
            continue  # own record by UUIDv5: skipped without comparing data
        owner = key_owner.get(value)
        if owner is not None and owner != record_id:
            conflicts.append(f"{table.name}: {code}: {key} = {value!r} занят записью {owner}")
    return conflicts


async def _translation_conflicts(
    conn: AsyncConnection,
    model: type[Base],
    parent_column: str,
    expected: list[tuple[str, UUID, UUID, str]],
) -> list[str]:
    """Expected (code, id, parent id, language); rule (b) of DEC-138."""
    table = table_of(model)
    ids = [record_id for _, record_id, _, _ in expected]
    parents = list({parent for _, _, parent, _ in expected})
    rows = (
        await conn.execute(
            select(table.c.id, table.c[parent_column], table.c.language_code).where(
                or_(table.c[parent_column].in_(parents), table.c.id.in_(ids))
            )
        )
    ).all()
    pairs = {(row[1], row[2]) for row in rows}
    pair_by_id = {row[0]: (row[1], row[2]) for row in rows}
    conflicts = []
    for code, record_id, parent, language in expected:
        if (parent, language) in pairs:
            continue  # existing pair: skipped, its id is not compared
        taken = pair_by_id.get(record_id)
        if taken is not None:
            conflicts.append(
                f"{table.name}: {code}: UUIDv5 {record_id} занят парой "
                f"({parent_column} = {taken[0]}, language_code = {taken[1]})"
            )
    return conflicts


def _translation_specs(
    parent_type: str, items: list[tuple[str, UUID, data.Names]]
) -> list[tuple[str, UUID, UUID, str]]:
    specs = []
    for parent_code, parent_id, names in items:
        for language, _name in names.items():
            code = data.translation_code(parent_type, parent_code, language)
            record_id = data.translation_id(parent_type, parent_code, language)
            specs.append((code, record_id, parent_id, language.value))
    return specs


async def collect_conflicts(conn: AsyncConnection) -> list[str]:
    """All natural-key and translation UUID conflicts, before any insert."""
    pv = [(p, v) for p in data.PRODUCTS for v in p.variants]
    gm = [(g, m) for g in data.MODIFIER_GROUPS for m in g.modifiers]
    conflicts: list[str] = []

    conflicts += await _natural_key_conflicts(
        conn,
        Category,
        "slug",
        [(data.category_code(c.slug), data.category_id(c.slug), c.slug) for c in data.CATEGORIES],
    )
    conflicts += await _natural_key_conflicts(
        conn,
        Product,
        "slug",
        [(data.product_code(p.code), data.product_id(p.code), p.slug) for p in data.PRODUCTS],
    )
    conflicts += await _natural_key_conflicts(
        conn,
        ProductVariant,
        "sku",
        [
            (data.variant_code(p.code, v.code), data.variant_id(p.code, v.code), v.sku)
            for p, v in pv
        ],
    )

    translation_checks: list[tuple[type[Base], str, list[tuple[str, UUID, UUID, str]]]] = [
        (
            CategoryTranslation,
            "category_id",
            _translation_specs(
                "category", [(c.slug, data.category_id(c.slug), c.names) for c in data.CATEGORIES]
            ),
        ),
        (
            ProductTranslation,
            "product_id",
            _translation_specs(
                "product", [(p.code, data.product_id(p.code), p.names) for p in data.PRODUCTS]
            ),
        ),
        (
            ProductVariantTranslation,
            "variant_id",
            _translation_specs(
                "variant",
                [
                    (
                        f"{p.code}.{v.code}",
                        data.variant_id(p.code, v.code),
                        data.VARIANT_NAMES[v.code],
                    )
                    for p, v in pv
                ],
            ),
        ),
        (
            ModifierGroupTranslation,
            "group_id",
            _translation_specs(
                "group", [(g.code, data.group_id(g.code), g.names) for g in data.MODIFIER_GROUPS]
            ),
        ),
        (
            ModifierTranslation,
            "modifier_id",
            _translation_specs(
                "modifier",
                [(f"{g.code}.{m.code}", data.modifier_id(g.code, m.code), m.names) for g, m in gm],
            ),
        ),
    ]
    for model, parent_column, specs in translation_checks:
        conflicts += await _translation_conflicts(conn, model, parent_column, specs)
    return conflicts


# --- Inserts --------------------------------------------------------------------


def demo_zone_row() -> dict[str, Any]:
    """The demo zone row; the geometry is built from the approved WKT and SRID."""
    zone = data.DEMO_ZONE
    return {
        "id": _demo_zone_id(),
        "name": zone.name,
        "description": zone.description,
        "delivery_fee": zone.delivery_fee,
        "min_order_amount": zone.min_order_amount,
        "is_active": True,
        "boundary": _approved_boundary(),
    }


async def insert_demo_rows(conn: AsyncConnection, report: SeedReport) -> None:
    """Insert missing rows, parents before children (13 tables)."""
    await insert_missing(conn, report, DeliveryZone, [demo_zone_row()])
    await insert_missing(conn, report, Category, data.category_rows())
    await insert_missing(conn, report, CategoryTranslation, data.category_translation_rows())
    await insert_missing(conn, report, ModifierGroup, data.modifier_group_rows())
    await insert_missing(
        conn, report, ModifierGroupTranslation, data.modifier_group_translation_rows()
    )
    await insert_missing(conn, report, Modifier, data.modifier_rows())
    await insert_missing(conn, report, ModifierTranslation, data.modifier_translation_rows())
    await insert_missing(conn, report, Product, data.product_rows())
    await insert_missing(conn, report, ProductTranslation, data.product_translation_rows())
    await insert_missing(conn, report, ProductModifierGroup, data.product_modifier_group_rows())
    await insert_missing(conn, report, ProductVariant, data.variant_rows())
    await insert_missing(conn, report, ProductVariantTranslation, data.variant_translation_rows())
    await insert_missing(conn, report, VariantModifierPrice, data.variant_modifier_price_rows())


async def seed_demo(conn: AsyncConnection) -> SeedReport:
    """Create missing `demo` records in the caller's transaction (no commit)."""
    await prepare_seed(conn)
    await check_base_ready(conn)
    await check_zone_overlap(conn)
    conflicts = await collect_conflicts(conn)
    if conflicts:
        raise SeedError(
            f"найдены конфликты demo-записей ({len(conflicts)}); демо-данные не созданы:\n"
            + "\n".join(f"  - {conflict}" for conflict in conflicts)
        )
    report = SeedReport()
    await insert_demo_rows(conn, report)
    return report
