"""Helpers shared by the catalog administration services."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.admin_catalog.schemas import TranslationIn, TranslationOut
from app.modules.admin_catalog.slugs import slugify, unique_slug

LANGUAGE_ORDER = {"ru": 0, "ky": 1, "uz": 2}


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def field_error(field: str, message: str) -> AppError:
    """422 VALIDATION_ERROR for a business rule on one field."""
    return AppError(
        422, "VALIDATION_ERROR", "Проверьте данные", details=[{"field": field, "message": message}]
    )


def ru_name(items: Iterable[TranslationIn]) -> str:
    return next(item.name for item in items if item.language_code == "ru")


async def replace_translations(
    session: AsyncSession,
    model: Any,
    owner_column: str,
    owner_id: uuid.UUID,
    items: list[TranslationIn],
) -> None:
    """Replace all translations of one record (the request array is the full set)."""
    table = model.__table__
    await session.execute(delete(table).where(table.c[owner_column] == owner_id))
    rows = []
    for item in items:
        row = {owner_column: owner_id, "language_code": item.language_code, "name": item.name}
        if "description" in table.c:
            row["description"] = item.description
        rows.append(row)
    await session.execute(insert(table), rows)


async def load_translations(
    session: AsyncSession, model: Any, owner_column: str, owner_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[TranslationOut]]:
    ids = list(owner_ids)
    result: dict[uuid.UUID, list[TranslationOut]] = defaultdict(list)
    if not ids:
        return result
    table = model.__table__
    has_description = "description" in table.c
    columns = [table.c[owner_column], table.c.language_code, table.c.name]
    if has_description:
        columns.append(table.c.description)
    rows = await session.execute(select(*columns).where(table.c[owner_column].in_(ids)))
    for row in rows:
        result[row[0]].append(
            TranslationOut(
                language_code=row.language_code,
                name=row.name,
                description=row.description if has_description else None,
            )
        )
    for items in result.values():
        items.sort(key=lambda t: LANGUAGE_ORDER.get(t.language_code, 9))
    return result


async def resolve_slug(
    session: AsyncSession,
    model: Any,
    *,
    requested: str | None,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """Requested slug if free, else 422; without a request, a unique slug from
    the Russian name (DEC-145)."""
    if requested:
        query = select(model.id).where(model.slug == requested)
        if exclude_id is not None:
            query = query.where(model.id != exclude_id)
        if await session.scalar(query):
            raise field_error("slug", "this slug is already used")
        return requested
    base = slugify(name)
    query = select(model.slug).where(model.slug.like(f"{base}%"))
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    taken = set((await session.scalars(query)).all())
    return unique_slug(base, taken)
