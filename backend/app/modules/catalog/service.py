"""Public catalog read model (API_SPECIFICATION.md §3).

Visibility rules:
- only active categories; products of inactive categories are hidden;
- soft-deleted products (`deleted_at`) are hidden;
- unavailable products, variants and modifiers are shown with
  `is_available = false` and are never offered as orderable;
- only active modifier groups linked to the product are shown.

Translations follow the fallback of `app.core.language`. Prices are read
from the database as they are; the frontend never computes them.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.language import pick
from app.modules.catalog.models import (
    Category,
    CategoryTranslation,
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
from app.modules.catalog.schemas import (
    CategoryList,
    CategoryOut,
    ImageOut,
    ModifierGroupOut,
    ModifierOut,
    Pagination,
    ProductDetail,
    ProductList,
    ProductSummary,
    VariantOut,
    VariantPriceOut,
)

MEDIA_URL_PREFIX = "/media"  # files are served from this path (stage 4B)


def media_url(path: str | None) -> str | None:
    return f"{MEDIA_URL_PREFIX}/{path.lstrip('/')}" if path else None


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


async def _translations(
    session: AsyncSession, model: Any, fk: Any, ids: Iterable[uuid.UUID], *columns: Any
) -> dict[uuid.UUID, dict[str, Any]]:
    """{entity_id: {language_code: row}} for the given translation table."""
    id_list = list(ids)
    result: dict[uuid.UUID, dict[str, Any]] = defaultdict(dict)
    if not id_list:
        return result
    rows = await session.execute(select(fk, model.language_code, *columns).where(fk.in_(id_list)))
    for row in rows:
        result[row[0]][row.language_code] = row
    return result


def _name(translations: dict[str, Any], chain: tuple[str, ...], fallback: str) -> tuple[str, Any]:
    row = pick(translations, chain)
    return (row.name if row else fallback), row


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------


async def list_categories(session: AsyncSession, chain: tuple[str, ...]) -> CategoryList:
    rows = (
        await session.execute(
            select(Category.id, Category.slug, Category.image_path, Category.sort_order)
            .where(Category.is_active)
            .order_by(Category.sort_order, Category.slug)
        )
    ).all()
    names = await _translations(
        session,
        CategoryTranslation,
        CategoryTranslation.category_id,
        (row.id for row in rows),
        CategoryTranslation.name,
        CategoryTranslation.description,
    )
    items = []
    for row in rows:
        name, tr = _name(names.get(row.id, {}), chain, row.slug)
        items.append(
            CategoryOut(
                id=row.id,
                slug=row.slug,
                name=name,
                description=tr.description if tr else None,
                image_url=media_url(row.image_path),
                sort_order=row.sort_order,
            )
        )
    return CategoryList(items=items)


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------


def _visible_products() -> Select:
    return (
        select(Product.id)
        .join(Category, Category.id == Product.category_id)
        .where(Product.deleted_at.is_(None), Category.is_active)
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _summaries(
    session: AsyncSession, product_ids: list[uuid.UUID], chain: tuple[str, ...]
) -> dict[uuid.UUID, ProductSummary]:
    if not product_ids:
        return {}
    products = (
        await session.execute(
            select(
                Product.id,
                Product.slug,
                Product.category_id,
                Product.is_available,
                Product.is_featured,
            ).where(Product.id.in_(product_ids))
        )
    ).all()
    names = await _translations(
        session,
        ProductTranslation,
        ProductTranslation.product_id,
        product_ids,
        ProductTranslation.name,
        ProductTranslation.description,
    )
    prices = dict(
        (
            await session.execute(
                select(ProductVariant.product_id, func.min(ProductVariant.price))
                .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_available)
                .group_by(ProductVariant.product_id)
            )
        ).all()
    )
    images: dict[uuid.UUID, str] = {}
    for row in await session.execute(
        select(ProductImage.product_id, ProductImage.image_path)
        .where(ProductImage.product_id.in_(product_ids))
        .order_by(ProductImage.product_id, ProductImage.is_primary.desc(), ProductImage.sort_order)
    ):
        images.setdefault(row.product_id, row.image_path)

    result = {}
    for row in products:
        name, tr = _name(names.get(row.id, {}), chain, row.slug)
        price_from: Decimal | None = prices.get(row.id)
        result[row.id] = ProductSummary(
            id=row.id,
            slug=row.slug,
            category_id=row.category_id,
            name=name,
            description=tr.description if tr else None,
            image_url=media_url(images.get(row.id)),
            # Orderable only if the product and at least one variant are available.
            is_available=row.is_available and price_from is not None,
            is_featured=row.is_featured,
            price_from=price_from,
        )
    return result


async def list_products(
    session: AsyncSession,
    chain: tuple[str, ...],
    *,
    category_id: uuid.UUID | None,
    search: str | None,
    featured: bool | None,
    page: int,
    page_size: int,
) -> ProductList:
    query = _visible_products()
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    if featured is not None:
        query = query.where(Product.is_featured.is_(featured))
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        query = query.where(
            exists().where(
                and_(
                    ProductTranslation.product_id == Product.id,
                    ProductTranslation.name.ilike(pattern, escape="\\"),
                )
            )
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    ids = list(
        (
            await session.scalars(
                query.order_by(Category.sort_order, Product.sort_order, Product.slug)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()
    )
    summaries = await _summaries(session, ids, chain)
    return ProductList(
        items=[summaries[product_id] for product_id in ids],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def get_product(
    session: AsyncSession, product_id: uuid.UUID, chain: tuple[str, ...]
) -> ProductDetail:
    visible = await session.scalar(_visible_products().where(Product.id == product_id))
    if visible is None:
        raise not_found()
    summary = (await _summaries(session, [product_id], chain))[product_id]

    images = [
        ImageOut(
            url=media_url(row.image_path) or "", alt_text=row.alt_text, is_primary=row.is_primary
        )
        for row in await session.execute(
            select(ProductImage.image_path, ProductImage.alt_text, ProductImage.is_primary)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order)
        )
    ]

    variant_rows = (
        await session.execute(
            select(
                ProductVariant.id,
                ProductVariant.sku,
                ProductVariant.price,
                ProductVariant.is_available,
            )
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.sort_order, ProductVariant.sku)
        )
    ).all()
    variant_names = await _translations(
        session,
        ProductVariantTranslation,
        ProductVariantTranslation.variant_id,
        (row.id for row in variant_rows),
        ProductVariantTranslation.name,
    )
    variants = [
        VariantOut(
            id=row.id,
            name=_name(variant_names.get(row.id, {}), chain, row.sku)[0],
            price=row.price,
            is_available=row.is_available,
        )
        for row in variant_rows
    ]

    return ProductDetail(
        **summary.model_dump(),
        images=images,
        variants=variants,
        modifier_groups=await _modifier_groups(
            session, product_id, [row.id for row in variant_rows], chain
        ),
    )


async def _modifier_groups(
    session: AsyncSession,
    product_id: uuid.UUID,
    variant_ids: list[uuid.UUID],
    chain: tuple[str, ...],
) -> list[ModifierGroupOut]:
    group_rows = (
        await session.execute(
            select(
                ModifierGroup.id,
                ModifierGroup.selection_type,
                ModifierGroup.is_required,
                ModifierGroup.min_selections,
                ModifierGroup.max_selections,
            )
            .join(ProductModifierGroup, ProductModifierGroup.group_id == ModifierGroup.id)
            .where(ProductModifierGroup.product_id == product_id, ModifierGroup.is_active)
            .order_by(ProductModifierGroup.sort_order, ModifierGroup.sort_order, ModifierGroup.id)
        )
    ).all()
    group_ids = [row.id for row in group_rows]
    if not group_ids:
        return []
    group_names = await _translations(
        session,
        ModifierGroupTranslation,
        ModifierGroupTranslation.group_id,
        group_ids,
        ModifierGroupTranslation.name,
        ModifierGroupTranslation.description,
    )
    modifier_rows = (
        await session.execute(
            select(
                Modifier.id,
                Modifier.group_id,
                Modifier.price_delta,
                Modifier.max_quantity,
                Modifier.is_available,
            )
            .where(Modifier.group_id.in_(group_ids))
            .order_by(Modifier.group_id, Modifier.sort_order, Modifier.id)
        )
    ).all()
    modifier_ids = [row.id for row in modifier_rows]
    modifier_names = await _translations(
        session,
        ModifierTranslation,
        ModifierTranslation.modifier_id,
        modifier_ids,
        ModifierTranslation.name,
        ModifierTranslation.description,
    )
    overrides: dict[uuid.UUID, list[VariantPriceOut]] = defaultdict(list)
    if modifier_ids and variant_ids:
        for row in await session.execute(
            select(
                VariantModifierPrice.modifier_id,
                VariantModifierPrice.variant_id,
                VariantModifierPrice.price_delta,
            ).where(
                VariantModifierPrice.modifier_id.in_(modifier_ids),
                VariantModifierPrice.variant_id.in_(variant_ids),
            )
        ):
            overrides[row.modifier_id].append(
                VariantPriceOut(variant_id=row.variant_id, price_delta=row.price_delta)
            )

    modifiers_by_group: dict[uuid.UUID, list[ModifierOut]] = defaultdict(list)
    for row in modifier_rows:
        name, tr = _name(modifier_names.get(row.id, {}), chain, str(row.id))
        modifiers_by_group[row.group_id].append(
            ModifierOut(
                id=row.id,
                name=name,
                description=tr.description if tr else None,
                price_delta=row.price_delta,
                max_quantity=row.max_quantity,
                is_available=row.is_available,
                variant_prices=sorted(overrides.get(row.id, []), key=lambda p: str(p.variant_id)),
            )
        )

    groups = []
    for row in group_rows:
        name, tr = _name(group_names.get(row.id, {}), chain, str(row.id))
        groups.append(
            ModifierGroupOut(
                id=row.id,
                name=name,
                description=tr.description if tr else None,
                selection_type=row.selection_type,
                is_required=row.is_required,
                min_selections=row.min_selections,
                max_selections=row.max_selections,
                modifiers=modifiers_by_group.get(row.id, []),
            )
        )
    return groups
