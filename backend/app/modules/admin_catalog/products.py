"""Products, variants, modifier group links, per-variant modifier prices and
images (API_SPECIFICATION.md §9 "Catalog").

Rules:
- a product has at least one variant (DEC-06); variants are never deleted
  here (they are referenced by carts and orders), only made unavailable;
- DELETE of a product sets `deleted_at` (soft delete, history is kept);
- a per-variant modifier price is accepted only for a modifier whose group
  is linked to the variant's product (DATABASE_SCHEMA.md §5.6);
- unlinking a group removes the per-variant prices of its modifiers for that
  product, so no stale override stays behind.
"""

import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import Select, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin_catalog import images
from app.modules.admin_catalog.common import (
    field_error,
    load_translations,
    not_found,
    replace_translations,
    resolve_slug,
    ru_name,
)
from app.modules.admin_catalog.schemas import (
    ImageAdminOut,
    ModifierPriceIn,
    ModifierPriceOut,
    ProductAdminDetail,
    ProductAdminList,
    ProductAdminSummary,
    ProductCreate,
    ProductGroupLink,
    ProductGroupOut,
    ProductUpdate,
    VariantAdminOut,
    VariantCreate,
    VariantUpdate,
)
from app.modules.catalog.models import (
    Category,
    Modifier,
    ModifierGroup,
    Product,
    ProductImage,
    ProductModifierGroup,
    ProductTranslation,
    ProductVariant,
    ProductVariantTranslation,
    VariantModifierPrice,
)
from app.modules.catalog.service import media_url


async def _require_category(session: AsyncSession, category_id: uuid.UUID) -> None:
    if await session.get(Category, category_id) is None:
        raise field_error("category_id", "category does not exist")


async def _sku_taken(session: AsyncSession, sku: str, exclude_id: uuid.UUID | None = None) -> bool:
    query = select(ProductVariant.id).where(func.lower(ProductVariant.sku) == sku.lower())
    if exclude_id is not None:
        query = query.where(ProductVariant.id != exclude_id)
    return await session.scalar(query) is not None


async def _check_new_skus(session: AsyncSession, variants: list[VariantCreate]) -> None:
    seen: set[str] = set()
    for index, variant in enumerate(variants):
        key = variant.sku.lower()
        if key in seen or await _sku_taken(session, variant.sku):
            raise field_error(f"variants.{index}.sku", "this SKU is already used")
        seen.add(key)


async def _insert_variant(
    session: AsyncSession, product_id: uuid.UUID, data: VariantCreate
) -> uuid.UUID:
    variant = ProductVariant(
        product_id=product_id,
        sku=data.sku,
        price=data.price,
        is_available=data.is_available,
        sort_order=data.sort_order,
    )
    session.add(variant)
    await session.flush()
    await replace_translations(
        session, ProductVariantTranslation, "variant_id", variant.id, data.translations
    )
    return variant.id


async def _commit_or_sku_conflict(session: AsyncSession, field: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None) or ""
        if "sku" in constraint:
            raise field_error(field, "this SKU is already used") from None
        raise


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------


def _filtered(category_id: uuid.UUID | None, search: str | None, status: str) -> Select:
    query = select(Product.id)
    if status == "active":
        query = query.where(Product.deleted_at.is_(None))
    elif status == "deleted":
        query = query.where(Product.deleted_at.is_not(None))
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    if search and search.strip():
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                Product.slug.ilike(f"%{escaped}%", escape="\\"),
                Product.id.in_(
                    select(ProductTranslation.product_id).where(
                        ProductTranslation.name.ilike(f"%{escaped}%", escape="\\")
                    )
                ),
            )
        )
    return query


async def list_products(
    session: AsyncSession,
    *,
    category_id: uuid.UUID | None,
    search: str | None,
    status: str,
    page: int,
    page_size: int,
) -> ProductAdminList:
    base = _filtered(category_id, search, status)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    products = (
        (
            await session.execute(
                select(Product)
                .where(Product.id.in_(base))
                .order_by(Product.sort_order, Product.slug)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        .scalars()
        .all()
    )
    ids = [p.id for p in products]
    names = await load_translations(session, ProductTranslation, "product_id", ids)
    stats = {
        row[0]: (row[1], row[2])
        for row in await session.execute(
            select(
                ProductVariant.product_id,
                func.min(ProductVariant.price).filter(ProductVariant.is_available),
                func.count(),
            )
            .where(ProductVariant.product_id.in_(ids))
            .group_by(ProductVariant.product_id)
        )
    }
    images_by_product: dict[uuid.UUID, str] = {}
    for row in await session.execute(
        select(ProductImage.product_id, ProductImage.image_path)
        .where(ProductImage.product_id.in_(ids))
        .order_by(ProductImage.product_id, ProductImage.is_primary.desc(), ProductImage.sort_order)
    ):
        images_by_product.setdefault(row.product_id, row.image_path)

    items = []
    for product in products:
        translations = names.get(product.id, [])
        ru = next((t.name for t in translations if t.language_code == "ru"), product.slug)
        price_from, count = stats.get(product.id, (None, 0))
        items.append(
            ProductAdminSummary(
                id=product.id,
                slug=product.slug,
                category_id=product.category_id,
                name=ru,
                is_available=product.is_available,
                is_featured=product.is_featured,
                sort_order=product.sort_order,
                deleted_at=product.deleted_at,
                price_from=price_from,
                variants_count=count,
                image_url=media_url(images_by_product.get(product.id)),
            )
        )
    return ProductAdminList(items=items, total=total)


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> ProductAdminDetail:
    product = await session.get(Product, product_id)
    if product is None:
        raise not_found()
    translations = await load_translations(session, ProductTranslation, "product_id", [product_id])
    variants = (
        (
            await session.execute(
                select(ProductVariant)
                .where(ProductVariant.product_id == product_id)
                .order_by(ProductVariant.sort_order, ProductVariant.sku)
            )
        )
        .scalars()
        .all()
    )
    variant_ids = [v.id for v in variants]
    variant_names = await load_translations(
        session, ProductVariantTranslation, "variant_id", variant_ids
    )
    prices: dict[uuid.UUID, list[ModifierPriceOut]] = {v: [] for v in variant_ids}
    if variant_ids:
        for row in await session.execute(
            select(
                VariantModifierPrice.variant_id,
                VariantModifierPrice.modifier_id,
                VariantModifierPrice.price_delta,
            ).where(VariantModifierPrice.variant_id.in_(variant_ids))
        ):
            prices[row.variant_id].append(
                ModifierPriceOut(modifier_id=row.modifier_id, price_delta=row.price_delta)
            )
    links = (
        await session.execute(
            select(ProductModifierGroup.group_id, ProductModifierGroup.sort_order)
            .where(ProductModifierGroup.product_id == product_id)
            .order_by(ProductModifierGroup.sort_order)
        )
    ).all()
    image_rows = (
        (
            await session.execute(
                select(ProductImage)
                .where(ProductImage.product_id == product_id)
                .order_by(
                    ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at
                )
            )
        )
        .scalars()
        .all()
    )
    return ProductAdminDetail(
        id=product.id,
        slug=product.slug,
        category_id=product.category_id,
        is_available=product.is_available,
        is_featured=product.is_featured,
        sort_order=product.sort_order,
        deleted_at=product.deleted_at,
        translations=translations.get(product_id, []),
        variants=[
            VariantAdminOut(
                id=v.id,
                sku=v.sku,
                price=v.price,
                is_available=v.is_available,
                sort_order=v.sort_order,
                translations=variant_names.get(v.id, []),
                modifier_prices=sorted(prices[v.id], key=lambda p: str(p.modifier_id)),
            )
            for v in variants
        ],
        modifier_groups=[ProductGroupOut(group_id=g, sort_order=s) for g, s in links],
        images=[
            ImageAdminOut(
                id=img.id,
                url=media_url(img.image_path) or "",
                alt_text=img.alt_text,
                sort_order=img.sort_order,
                is_primary=img.is_primary,
            )
            for img in image_rows
        ],
    )


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------


async def create_product(session: AsyncSession, data: ProductCreate) -> ProductAdminDetail:
    await _require_category(session, data.category_id)
    await _check_new_skus(session, data.variants)
    slug = await resolve_slug(
        session, Product, requested=data.slug, name=ru_name(data.translations)
    )
    product = Product(
        category_id=data.category_id,
        slug=slug,
        is_available=data.is_available,
        is_featured=data.is_featured,
        sort_order=data.sort_order,
    )
    session.add(product)
    await session.flush()
    await replace_translations(
        session, ProductTranslation, "product_id", product.id, data.translations
    )
    for variant in data.variants:
        await _insert_variant(session, product.id, variant)
    await _commit_or_sku_conflict(session, "variants")
    return await get_product(session, product.id)


async def _load_product(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise not_found()
    return product


async def update_product(
    session: AsyncSession, product_id: uuid.UUID, data: ProductUpdate
) -> ProductAdminDetail:
    product = await _load_product(session, product_id)
    if data.category_id is not None:
        await _require_category(session, data.category_id)
        product.category_id = data.category_id
    if data.slug is not None:
        product.slug = await resolve_slug(
            session, Product, requested=data.slug, name="", exclude_id=product.id
        )
    for field in ("is_available", "is_featured", "sort_order"):
        value = getattr(data, field)
        if value is not None:
            setattr(product, field, value)
    if data.translations is not None:
        await replace_translations(
            session, ProductTranslation, "product_id", product.id, data.translations
        )
    await session.commit()
    return await get_product(session, product_id)


async def delete_product(session: AsyncSession, product_id: uuid.UUID) -> None:
    """Soft delete: `deleted_at` is set once; the product leaves the public
    catalog, order history keeps its snapshots."""
    product = await _load_product(session, product_id)
    if product.deleted_at is None:
        product.deleted_at = datetime.now(UTC)
    await session.commit()


async def add_variant(
    session: AsyncSession, product_id: uuid.UUID, data: VariantCreate
) -> ProductAdminDetail:
    await _load_product(session, product_id)
    if await _sku_taken(session, data.sku):
        raise field_error("sku", "this SKU is already used")
    await _insert_variant(session, product_id, data)
    await _commit_or_sku_conflict(session, "sku")
    return await get_product(session, product_id)


async def update_variant(
    session: AsyncSession, variant_id: uuid.UUID, data: VariantUpdate
) -> ProductAdminDetail:
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise not_found()
    if data.sku is not None:
        if await _sku_taken(session, data.sku, exclude_id=variant.id):
            raise field_error("sku", "this SKU is already used")
        variant.sku = data.sku
    for field in ("price", "is_available", "sort_order"):
        value = getattr(data, field)
        if value is not None:
            setattr(variant, field, value)
    if data.translations is not None:
        await replace_translations(
            session, ProductVariantTranslation, "variant_id", variant.id, data.translations
        )
    product_id = variant.product_id
    await _commit_or_sku_conflict(session, "sku")
    return await get_product(session, product_id)


async def put_modifier_prices(
    session: AsyncSession, variant_id: uuid.UUID, items: list[ModifierPriceIn]
) -> ProductAdminDetail:
    """Replace all per-variant modifier prices of one variant (§5.6)."""
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise not_found()
    ids = [item.modifier_id for item in items]
    if len(ids) != len(set(ids)):
        raise field_error("items", "each modifier may appear only once")
    if ids:
        allowed = set(
            (
                await session.scalars(
                    select(Modifier.id)
                    .join(ProductModifierGroup, ProductModifierGroup.group_id == Modifier.group_id)
                    .where(
                        ProductModifierGroup.product_id == variant.product_id,
                        Modifier.id.in_(ids),
                    )
                )
            ).all()
        )
        for index, modifier_id in enumerate(ids):
            if modifier_id not in allowed:
                raise field_error(
                    f"{index}.modifier_id", "the modifier's group is not linked to this product"
                )
    table = VariantModifierPrice.__table__
    await session.execute(delete(table).where(table.c.variant_id == variant_id))
    if items:
        await session.execute(
            insert(table),
            [
                {
                    "variant_id": variant_id,
                    "modifier_id": i.modifier_id,
                    "price_delta": i.price_delta,
                }
                for i in items
            ],
        )
    product_id = variant.product_id
    await session.commit()
    return await get_product(session, product_id)


async def put_modifier_groups(
    session: AsyncSession, product_id: uuid.UUID, links: list[ProductGroupLink]
) -> ProductAdminDetail:
    """Replace the set of modifier groups offered for a product."""
    await _load_product(session, product_id)
    group_ids = [link.group_id for link in links]
    if len(group_ids) != len(set(group_ids)):
        raise field_error("items", "each group may appear only once")
    if group_ids:
        existing = set(
            (
                await session.scalars(
                    select(ModifierGroup.id).where(ModifierGroup.id.in_(group_ids))
                )
            ).all()
        )
        for index, group_id in enumerate(group_ids):
            if group_id not in existing:
                raise field_error(f"{index}.group_id", "group does not exist")
    links_table = ProductModifierGroup.__table__
    await session.execute(delete(links_table).where(links_table.c.product_id == product_id))
    if links:
        await session.execute(
            insert(links_table),
            [
                {"product_id": product_id, "group_id": link.group_id, "sort_order": link.sort_order}
                for link in links
            ],
        )
    # Per-variant prices of modifiers whose group is no longer linked.
    prices = VariantModifierPrice.__table__
    stale = select(Modifier.id)
    if group_ids:
        stale = stale.where(Modifier.group_id.not_in(group_ids))
    await session.execute(
        delete(prices).where(
            prices.c.variant_id.in_(
                select(ProductVariant.id).where(ProductVariant.product_id == product_id)
            ),
            prices.c.modifier_id.in_(stale),
        )
    )
    await session.commit()
    return await get_product(session, product_id)


async def add_image(
    session: AsyncSession,
    product_id: uuid.UUID,
    upload: UploadFile,
    alt_text: str | None,
    make_primary: bool,
) -> ProductAdminDetail:
    await _load_product(session, product_id)
    data, extension = await images.validate_upload(upload)
    has_primary = await session.scalar(
        select(ProductImage.id).where(
            ProductImage.product_id == product_id, ProductImage.is_primary
        )
    )
    primary = make_primary or has_primary is None  # the first image becomes primary
    next_order = (
        await session.scalar(
            select(func.coalesce(func.max(ProductImage.sort_order), -1)).where(
                ProductImage.product_id == product_id
            )
        )
    ) + 1
    stored = images.store(data, "products", extension)
    try:
        if primary:
            await session.execute(
                update(ProductImage)
                .where(ProductImage.product_id == product_id)
                .values(is_primary=False)
            )
        session.add(
            ProductImage(
                product_id=product_id,
                image_path=stored.key,
                alt_text=(alt_text or "").strip()[:255] or None,
                sort_order=next_order,
                is_primary=primary,
            )
        )
        await session.commit()
    except Exception:
        images.remove(stored.key)
        raise
    return await get_product(session, product_id)


async def delete_image(session: AsyncSession, product_id: uuid.UUID, image_id: uuid.UUID) -> None:
    image = await session.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        raise not_found()
    key = image.image_path
    await session.delete(image)
    await session.commit()
    images.remove(key)
