"""Modifier groups and modifiers.

Group rules (DATABASE_SCHEMA.md §5.1, DEC-58, DEC-81, DEC-128):
- `single` groups allow exactly one choice: `max_selections` must be 1;
- `min_selections <= max_selections` when max is set (NULL = no limit);
- `is_required` is derived: required exactly when `min_selections >= 1`;
- min/max count distinct modifiers; `max_quantity` limits one modifier.
Groups and modifiers are never deleted (they may be in order history);
they are switched off with `is_active` / `is_available`.
"""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin_catalog.common import (
    field_error,
    load_translations,
    not_found,
    replace_translations,
)
from app.modules.admin_catalog.schemas import (
    ModifierAdminList,
    ModifierAdminOut,
    ModifierCreate,
    ModifierGroupAdminList,
    ModifierGroupAdminOut,
    ModifierGroupCreate,
    ModifierGroupUpdate,
    ModifierUpdate,
)
from app.modules.catalog.models import (
    Modifier,
    ModifierGroup,
    ModifierGroupTranslation,
    ModifierTranslation,
    ProductModifierGroup,
)


def check_group_rules(selection_type: str, min_selections: int, max_selections: int | None) -> None:
    if selection_type == "single" and max_selections != 1:
        raise field_error("max_selections", "a single-choice group allows exactly one option")
    if max_selections is not None and min_selections > max_selections:
        raise field_error("min_selections", "minimum must not exceed maximum")


async def _modifiers_out(session: AsyncSession, query) -> list[ModifierAdminOut]:  # noqa: ANN001 - SQLAlchemy Select
    rows = (await session.execute(query)).scalars().all()
    names = await load_translations(
        session, ModifierTranslation, "modifier_id", [m.id for m in rows]
    )
    return [
        ModifierAdminOut(
            id=m.id,
            group_id=m.group_id,
            price_delta=m.price_delta,
            max_quantity=m.max_quantity,
            is_available=m.is_available,
            sort_order=m.sort_order,
            translations=names.get(m.id, []),
        )
        for m in rows
    ]


async def _groups_out(
    session: AsyncSession, group_ids: list[uuid.UUID]
) -> list[ModifierGroupAdminOut]:
    groups = (
        (
            await session.execute(
                select(ModifierGroup)
                .where(ModifierGroup.id.in_(group_ids))
                .order_by(ModifierGroup.sort_order, ModifierGroup.id)
            )
        )
        .scalars()
        .all()
    )
    names = await load_translations(session, ModifierGroupTranslation, "group_id", group_ids)
    modifiers = await _modifiers_out(
        session,
        select(Modifier)
        .where(Modifier.group_id.in_(group_ids))
        .order_by(Modifier.sort_order, Modifier.id),
    )
    by_group: dict[uuid.UUID, list[ModifierAdminOut]] = defaultdict(list)
    for modifier in modifiers:
        by_group[modifier.group_id].append(modifier)
    usage = dict(
        (
            await session.execute(
                select(ProductModifierGroup.group_id, func.count())
                .where(ProductModifierGroup.group_id.in_(group_ids))
                .group_by(ProductModifierGroup.group_id)
            )
        ).all()
    )
    return [
        ModifierGroupAdminOut(
            id=g.id,
            selection_type=g.selection_type,
            is_required=g.is_required,
            min_selections=g.min_selections,
            max_selections=g.max_selections,
            is_active=g.is_active,
            sort_order=g.sort_order,
            translations=names.get(g.id, []),
            modifiers=by_group.get(g.id, []),
            products_count=usage.get(g.id, 0),
        )
        for g in groups
    ]


async def list_groups(session: AsyncSession) -> ModifierGroupAdminList:
    ids = list((await session.scalars(select(ModifierGroup.id))).all())
    return ModifierGroupAdminList(items=await _groups_out(session, ids))


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> ModifierGroupAdminOut:
    items = await _groups_out(session, [group_id])
    if not items:
        raise not_found()
    return items[0]


async def create_group(session: AsyncSession, data: ModifierGroupCreate) -> ModifierGroupAdminOut:
    check_group_rules(data.selection_type, data.min_selections, data.max_selections)
    group = ModifierGroup(
        selection_type=data.selection_type,
        is_required=data.min_selections >= 1,
        min_selections=data.min_selections,
        max_selections=data.max_selections,
        is_active=data.is_active,
        sort_order=data.sort_order,
    )
    session.add(group)
    await session.flush()
    await replace_translations(
        session, ModifierGroupTranslation, "group_id", group.id, data.translations
    )
    await session.commit()
    return await get_group(session, group.id)


async def update_group(
    session: AsyncSession, group_id: uuid.UUID, data: ModifierGroupUpdate
) -> ModifierGroupAdminOut:
    group = await session.get(ModifierGroup, group_id)
    if group is None:
        raise not_found()
    selection_type = data.selection_type or group.selection_type
    min_selections = (
        data.min_selections if data.min_selections is not None else group.min_selections
    )
    if data.clear_max_selections:
        max_selections = None
    elif data.max_selections is not None:
        max_selections = data.max_selections
    else:
        max_selections = group.max_selections
    check_group_rules(selection_type, min_selections, max_selections)
    group.selection_type = selection_type
    group.min_selections = min_selections
    group.max_selections = max_selections
    group.is_required = min_selections >= 1
    if data.is_active is not None:
        group.is_active = data.is_active
    if data.sort_order is not None:
        group.sort_order = data.sort_order
    if data.translations is not None:
        await replace_translations(
            session, ModifierGroupTranslation, "group_id", group.id, data.translations
        )
    await session.commit()
    return await get_group(session, group_id)


async def list_modifiers(session: AsyncSession, group_id: uuid.UUID | None) -> ModifierAdminList:
    query = select(Modifier).order_by(Modifier.group_id, Modifier.sort_order, Modifier.id)
    if group_id is not None:
        query = query.where(Modifier.group_id == group_id)
    return ModifierAdminList(items=await _modifiers_out(session, query))


async def _modifier_out(session: AsyncSession, modifier_id: uuid.UUID) -> ModifierAdminOut:
    items = await _modifiers_out(session, select(Modifier).where(Modifier.id == modifier_id))
    if not items:
        raise not_found()
    return items[0]


async def create_modifier(session: AsyncSession, data: ModifierCreate) -> ModifierAdminOut:
    if await session.get(ModifierGroup, data.group_id) is None:
        raise field_error("group_id", "group does not exist")
    modifier = Modifier(
        group_id=data.group_id,
        price_delta=data.price_delta,
        max_quantity=data.max_quantity,
        is_available=data.is_available,
        sort_order=data.sort_order,
    )
    session.add(modifier)
    await session.flush()
    await replace_translations(
        session, ModifierTranslation, "modifier_id", modifier.id, data.translations
    )
    await session.commit()
    return await _modifier_out(session, modifier.id)


async def update_modifier(
    session: AsyncSession, modifier_id: uuid.UUID, data: ModifierUpdate
) -> ModifierAdminOut:
    modifier = await session.get(Modifier, modifier_id)
    if modifier is None:
        raise not_found()
    for field in ("price_delta", "max_quantity", "is_available", "sort_order"):
        value = getattr(data, field)
        if value is not None:
            setattr(modifier, field, value)
    if data.translations is not None:
        await replace_translations(
            session, ModifierTranslation, "modifier_id", modifier.id, data.translations
        )
    await session.commit()
    return await _modifier_out(session, modifier_id)
