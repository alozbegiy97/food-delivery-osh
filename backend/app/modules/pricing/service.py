"""Catalog snapshot, selection validation and line prices (DEC-08).

Rules (DATABASE_SCHEMA.md §5.6, §5.7, DEC-81, DEC-128):
- the product exists, is not soft-deleted, its category is active and the
  product is available; the variant belongs to the product and is
  available;
- each selected modifier exists and is available, its group is active and
  linked to the product; `1 <= quantity <= max_quantity`;
- per active linked group: the number of DIFFERENT selected modifiers is
  within `min_selections..max_selections`; required groups are not empty;
  a `single` group has at most one option;
- modifier price for a variant: the `variant_modifier_prices` override if
  present, otherwise `modifiers.price_delta`;
- unit price = variant price + Σ(modifier price × modifier quantity);
  line total = unit price × line quantity (DEC-61).

The client never sends prices; everything here is read from the database
at the moment of the calculation.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.language import pick
from app.modules.catalog.enums import SelectionType
from app.modules.catalog.models import (
    Category,
    Modifier,
    ModifierGroup,
    ModifierGroupTranslation,
    ModifierTranslation,
    Product,
    ProductImage,
    ProductModifierGroup,
    ProductTranslation,
    ProductVariant,
    ProductVariantTranslation,
    VariantModifierPrice,
)
from app.modules.catalog.service import media_url

ZERO = Decimal("0.00")

# Issue codes (shown per cart line; the frontend translates them).
PRODUCT_UNAVAILABLE = "PRODUCT_UNAVAILABLE"
VARIANT_UNAVAILABLE = "VARIANT_UNAVAILABLE"
MODIFIER_UNAVAILABLE = "MODIFIER_UNAVAILABLE"
MODIFIER_QUANTITY_EXCEEDED = "MODIFIER_QUANTITY_EXCEEDED"
GROUP_REQUIRED = "GROUP_REQUIRED"
GROUP_MIN_SELECTIONS = "GROUP_MIN_SELECTIONS"
GROUP_MAX_SELECTIONS = "GROUP_MAX_SELECTIONS"

AVAILABILITY_ISSUES = frozenset({PRODUCT_UNAVAILABLE, VARIANT_UNAVAILABLE, MODIFIER_UNAVAILABLE})


@dataclass(frozen=True)
class Issue:
    code: str
    group_id: uuid.UUID | None = None
    modifier_id: uuid.UUID | None = None
    group_name: str | None = None
    modifier_name: str | None = None
    limit: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "group_id": str(self.group_id) if self.group_id else None,
            "modifier_id": str(self.modifier_id) if self.modifier_id else None,
            "group_name": self.group_name,
            "modifier_name": self.modifier_name,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class VariantInfo:
    id: uuid.UUID
    product_id: uuid.UUID
    price: Decimal
    is_available: bool
    name: str
    sku: str


@dataclass(frozen=True)
class GroupInfo:
    id: uuid.UUID
    selection_type: str
    is_required: bool
    min_selections: int
    max_selections: int | None
    is_active: bool
    name: str


@dataclass(frozen=True)
class ModifierInfo:
    id: uuid.UUID
    group_id: uuid.UUID
    price_delta: Decimal
    max_quantity: int
    is_available: bool
    name: str


@dataclass(frozen=True)
class ProductInfo:
    id: uuid.UUID
    name: str
    image_url: str | None
    # Not soft-deleted, category active and the product itself available.
    orderable: bool
    # Groups linked to the product, in display order.
    group_ids: tuple[uuid.UUID, ...]


@dataclass
class CatalogSnapshot:
    products: dict[uuid.UUID, ProductInfo] = field(default_factory=dict)
    variants: dict[uuid.UUID, VariantInfo] = field(default_factory=dict)
    groups: dict[uuid.UUID, GroupInfo] = field(default_factory=dict)
    modifiers: dict[uuid.UUID, ModifierInfo] = field(default_factory=dict)
    # (variant_id, modifier_id) -> price_delta override
    overrides: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = field(default_factory=dict)

    def modifier_price(self, variant_id: uuid.UUID, modifier: ModifierInfo) -> Decimal:
        return self.overrides.get((variant_id, modifier.id), modifier.price_delta)


@dataclass(frozen=True)
class PricedModifier:
    modifier_id: uuid.UUID
    group_id: uuid.UUID | None
    name: str
    group_name: str | None
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class LineEvaluation:
    issues: tuple[Issue, ...]
    # Price of one unit; None if the variant does not exist for the product.
    unit_price: Decimal | None
    modifiers: tuple[PricedModifier, ...]
    # Price of the size alone, without extras (order snapshot, DEC-61).
    variant_price: Decimal | None = None

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def line_total(self, quantity: int) -> Decimal | None:
        return None if self.unit_price is None else self.unit_price * quantity


async def _names(
    session: AsyncSession, model: Any, fk: Any, ids: Iterable[uuid.UUID], chain: tuple[str, ...]
) -> dict[uuid.UUID, str]:
    id_list = list(ids)
    if not id_list:
        return {}
    rows = await session.execute(select(fk, model.language_code, model.name).where(fk.in_(id_list)))
    by_owner: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    for owner_id, language, name in rows:
        by_owner[owner_id][language] = name
    return {owner: pick(names, chain) or "" for owner, names in by_owner.items()}


async def load_catalog(
    session: AsyncSession,
    product_ids: Iterable[uuid.UUID],
    modifier_ids: Iterable[uuid.UUID],
    chain: tuple[str, ...],
) -> CatalogSnapshot:
    """Everything needed to validate and price the given selections."""
    snapshot = CatalogSnapshot()
    product_list = list(set(product_ids))
    modifier_list = list(set(modifier_ids))
    if not product_list:
        return snapshot

    product_rows = (
        await session.execute(
            select(
                Product.id,
                Product.slug,
                Product.is_available,
                Product.deleted_at,
                Category.is_active.label("category_active"),
            )
            .join(Category, Category.id == Product.category_id)
            .where(Product.id.in_(product_list))
        )
    ).all()
    found = [row.id for row in product_rows]
    product_names = await _names(
        session, ProductTranslation, ProductTranslation.product_id, found, chain
    )
    images: dict[uuid.UUID, str] = {}
    for product_id, path in await session.execute(
        select(ProductImage.product_id, ProductImage.image_path)
        .where(ProductImage.product_id.in_(found))
        .order_by(
            ProductImage.product_id,
            ProductImage.is_primary.desc(),
            ProductImage.sort_order,
            ProductImage.created_at,
        )
    ):
        images.setdefault(product_id, path)

    links: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for product_id, group_id in await session.execute(
        select(ProductModifierGroup.product_id, ProductModifierGroup.group_id)
        .where(ProductModifierGroup.product_id.in_(found))
        .order_by(ProductModifierGroup.product_id, ProductModifierGroup.sort_order)
    ):
        links[product_id].append(group_id)

    for row in product_rows:
        snapshot.products[row.id] = ProductInfo(
            id=row.id,
            name=product_names.get(row.id) or row.slug,
            image_url=media_url(images.get(row.id)),
            orderable=row.deleted_at is None and row.category_active and row.is_available,
            group_ids=tuple(links.get(row.id, [])),
        )

    variant_rows = (
        await session.execute(
            select(
                ProductVariant.id,
                ProductVariant.product_id,
                ProductVariant.sku,
                ProductVariant.price,
                ProductVariant.is_available,
            ).where(ProductVariant.product_id.in_(found))
        )
    ).all()
    variant_names = await _names(
        session,
        ProductVariantTranslation,
        ProductVariantTranslation.variant_id,
        (row.id for row in variant_rows),
        chain,
    )
    for row in variant_rows:
        snapshot.variants[row.id] = VariantInfo(
            id=row.id,
            product_id=row.product_id,
            price=row.price,
            is_available=row.is_available,
            name=variant_names.get(row.id) or row.sku,
            sku=row.sku,
        )

    modifier_rows = (
        (
            await session.execute(
                select(
                    Modifier.id,
                    Modifier.group_id,
                    Modifier.price_delta,
                    Modifier.max_quantity,
                    Modifier.is_available,
                ).where(Modifier.id.in_(modifier_list))
            )
        ).all()
        if modifier_list
        else []
    )
    modifier_names = await _names(
        session,
        ModifierTranslation,
        ModifierTranslation.modifier_id,
        (row.id for row in modifier_rows),
        chain,
    )
    for row in modifier_rows:
        snapshot.modifiers[row.id] = ModifierInfo(
            id=row.id,
            group_id=row.group_id,
            price_delta=row.price_delta,
            max_quantity=row.max_quantity,
            is_available=row.is_available,
            name=modifier_names.get(row.id) or "",
        )

    group_ids = {g for ids in links.values() for g in ids} | {row.group_id for row in modifier_rows}
    if group_ids:
        group_names = await _names(
            session, ModifierGroupTranslation, ModifierGroupTranslation.group_id, group_ids, chain
        )
        for row in await session.execute(
            select(
                ModifierGroup.id,
                ModifierGroup.selection_type,
                ModifierGroup.is_required,
                ModifierGroup.min_selections,
                ModifierGroup.max_selections,
                ModifierGroup.is_active,
            ).where(ModifierGroup.id.in_(group_ids))
        ):
            snapshot.groups[row.id] = GroupInfo(
                id=row.id,
                selection_type=row.selection_type,
                is_required=row.is_required,
                min_selections=row.min_selections,
                max_selections=row.max_selections,
                is_active=row.is_active,
                name=group_names.get(row.id) or "",
            )

    if modifier_rows and variant_rows:
        for variant_id, modifier_id, price in await session.execute(
            select(
                VariantModifierPrice.variant_id,
                VariantModifierPrice.modifier_id,
                VariantModifierPrice.price_delta,
            ).where(
                VariantModifierPrice.variant_id.in_([row.id for row in variant_rows]),
                VariantModifierPrice.modifier_id.in_([row.id for row in modifier_rows]),
            )
        ):
            snapshot.overrides[(variant_id, modifier_id)] = price
    return snapshot


def evaluate_line(
    catalog: CatalogSnapshot,
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    modifiers: Mapping[uuid.UUID, int],
) -> LineEvaluation:
    """Validate one selection (§5.7) and price one unit of it."""
    issues: list[Issue] = []
    product = catalog.products.get(product_id)
    if product is None or not product.orderable:
        issues.append(Issue(PRODUCT_UNAVAILABLE))
    variant = catalog.variants.get(variant_id)
    if variant is None or variant.product_id != product_id:
        variant = None
        issues.append(Issue(VARIANT_UNAVAILABLE))
    elif not variant.is_available:
        issues.append(Issue(VARIANT_UNAVAILABLE))

    linked = set(product.group_ids) if product else set()
    per_group: dict[uuid.UUID, int] = defaultdict(int)
    priced: list[PricedModifier] = []
    for modifier_id, quantity in modifiers.items():
        modifier = catalog.modifiers.get(modifier_id)
        group = catalog.groups.get(modifier.group_id) if modifier else None
        if modifier is None:
            issues.append(Issue(MODIFIER_UNAVAILABLE, modifier_id=modifier_id))
            continue
        if (
            not modifier.is_available
            or group is None
            or not group.is_active
            or modifier.group_id not in linked
        ):
            issues.append(
                Issue(
                    MODIFIER_UNAVAILABLE,
                    group_id=modifier.group_id,
                    modifier_id=modifier.id,
                    group_name=group.name if group else None,
                    modifier_name=modifier.name,
                )
            )
        elif quantity > modifier.max_quantity:
            issues.append(
                Issue(
                    MODIFIER_QUANTITY_EXCEEDED,
                    group_id=group.id,
                    modifier_id=modifier.id,
                    group_name=group.name,
                    modifier_name=modifier.name,
                    limit=modifier.max_quantity,
                )
            )
        per_group[modifier.group_id] += 1
        priced.append(
            PricedModifier(
                modifier_id=modifier.id,
                group_id=modifier.group_id,
                name=modifier.name,
                group_name=group.name if group else None,
                quantity=quantity,
                unit_price=catalog.modifier_price(variant_id, modifier) if variant else ZERO,
            )
        )

    if product is not None:
        for group_id in product.group_ids:
            group = catalog.groups.get(group_id)
            if group is None or not group.is_active:
                continue
            chosen = per_group.get(group_id, 0)
            maximum = 1 if group.selection_type == SelectionType.SINGLE.value else None
            if group.max_selections is not None:
                maximum = (
                    group.max_selections if maximum is None else min(maximum, group.max_selections)
                )
            if chosen == 0 and (group.is_required or group.min_selections > 0):
                issues.append(Issue(GROUP_REQUIRED, group_id=group.id, group_name=group.name))
            elif chosen < group.min_selections:
                issues.append(
                    Issue(
                        GROUP_MIN_SELECTIONS,
                        group_id=group.id,
                        group_name=group.name,
                        limit=group.min_selections,
                    )
                )
            elif maximum is not None and chosen > maximum:
                issues.append(
                    Issue(
                        GROUP_MAX_SELECTIONS,
                        group_id=group.id,
                        group_name=group.name,
                        limit=maximum,
                    )
                )

    order = {group_id: index for index, group_id in enumerate(product.group_ids if product else ())}
    priced.sort(key=lambda m: order.get(m.group_id, len(order)) if m.group_id else len(order))
    unit_price = None
    if variant is not None:
        unit_price = variant.price + sum((m.unit_price * m.quantity for m in priced), start=ZERO)
    return LineEvaluation(
        issues=tuple(issues),
        unit_price=unit_price,
        modifiers=tuple(priced),
        variant_price=variant.price if variant is not None else None,
    )


def selection_error(issues: Iterable[Issue]) -> AppError:
    """422 for an invalid selection: ITEM_UNAVAILABLE if anything is not
    available, otherwise MODIFIER_CONSTRAINT_VIOLATION (API §1.1)."""
    issue_list = list(issues)
    if any(issue.code in AVAILABILITY_ISSUES for issue in issue_list):
        return AppError(
            422,
            "ITEM_UNAVAILABLE",
            "Товар, размер или добавка недоступны",
            details=[issue.as_dict() for issue in issue_list],
        )
    return AppError(
        422,
        "MODIFIER_CONSTRAINT_VIOLATION",
        "Нарушены правила выбора добавок",
        details=[issue.as_dict() for issue in issue_list],
    )
