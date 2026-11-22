"""Categories: list, create, update, deactivate (DEC-26), image."""

import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin_catalog import images
from app.modules.admin_catalog.common import (
    load_translations,
    not_found,
    replace_translations,
    resolve_slug,
    ru_name,
)
from app.modules.admin_catalog.schemas import (
    CategoryAdminList,
    CategoryAdminOut,
    CategoryCreate,
    CategoryUpdate,
)
from app.modules.catalog.models import Category, CategoryTranslation, Product
from app.modules.catalog.service import media_url


async def _out(session: AsyncSession, category_ids: list[uuid.UUID]) -> list[CategoryAdminOut]:
    rows = (
        (
            await session.execute(
                select(Category)
                .where(Category.id.in_(category_ids))
                .order_by(Category.sort_order, Category.slug)
            )
        )
        .scalars()
        .all()
    )
    names = await load_translations(session, CategoryTranslation, "category_id", category_ids)
    counts = dict(
        (
            await session.execute(
                select(Product.category_id, func.count())
                .where(Product.category_id.in_(category_ids), Product.deleted_at.is_(None))
                .group_by(Product.category_id)
            )
        ).all()
    )
    return [
        CategoryAdminOut(
            id=row.id,
            slug=row.slug,
            sort_order=row.sort_order,
            is_active=row.is_active,
            image_url=media_url(row.image_path),
            translations=names.get(row.id, []),
            products_count=counts.get(row.id, 0),
        )
        for row in rows
    ]


async def list_categories(session: AsyncSession) -> CategoryAdminList:
    ids = list((await session.scalars(select(Category.id))).all())
    return CategoryAdminList(items=await _out(session, ids))


async def get_category(session: AsyncSession, category_id: uuid.UUID) -> CategoryAdminOut:
    items = await _out(session, [category_id])
    if not items:
        raise not_found()
    return items[0]


async def create_category(session: AsyncSession, data: CategoryCreate) -> CategoryAdminOut:
    slug = await resolve_slug(
        session, Category, requested=data.slug, name=ru_name(data.translations)
    )
    category = Category(slug=slug, sort_order=data.sort_order, is_active=data.is_active)
    session.add(category)
    await session.flush()
    await replace_translations(
        session, CategoryTranslation, "category_id", category.id, data.translations
    )
    await session.commit()
    return await get_category(session, category.id)


async def _load(session: AsyncSession, category_id: uuid.UUID) -> Category:
    category = await session.get(Category, category_id)
    if category is None:
        raise not_found()
    return category


async def update_category(
    session: AsyncSession, category_id: uuid.UUID, data: CategoryUpdate
) -> CategoryAdminOut:
    category = await _load(session, category_id)
    if data.slug is not None:
        category.slug = await resolve_slug(
            session, Category, requested=data.slug, name="", exclude_id=category.id
        )
    if data.sort_order is not None:
        category.sort_order = data.sort_order
    if data.is_active is not None:
        category.is_active = data.is_active
    if data.translations is not None:
        await replace_translations(
            session, CategoryTranslation, "category_id", category.id, data.translations
        )
    await session.commit()
    return await get_category(session, category_id)


async def deactivate_category(session: AsyncSession, category_id: uuid.UUID) -> None:
    """DELETE = deactivation (DEC-26); products stay and are hidden publicly."""
    category = await _load(session, category_id)
    category.is_active = False
    await session.commit()


async def set_category_image(
    session: AsyncSession, category_id: uuid.UUID, upload: UploadFile
) -> CategoryAdminOut:
    category = await _load(session, category_id)
    data, extension = await images.validate_upload(upload)
    stored = images.store(data, "categories", extension)
    old_key = category.image_path
    category.image_path = stored.key
    try:
        await session.commit()
    except Exception:
        images.remove(stored.key)
        raise
    images.remove(old_key)
    return await get_category(session, category_id)
