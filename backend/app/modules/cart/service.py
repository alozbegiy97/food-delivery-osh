"""Server-side cart (API_SPECIFICATION.md §5, DATABASE_SCHEMA.md §6).

- one cart per customer, created on the first add; GET never writes;
- every change locks the user's cart row (`SELECT … FOR UPDATE`), so
  concurrent requests of one user are applied one after another and the
  merge (DEC-11) never creates duplicate lines;
- a new line is validated by the shared pricing module before it is saved;
  stored lines are re-validated and re-priced on every read (DEC-08);
- PATCH changes only the quantity and the instructions; equal lines are
  merged afterwards (DEC-12);
- limits: quantity 1..99 per line (also after a merge), at most 50 lines,
  instructions up to 500 characters (DEC-146).
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.cart.models import Cart, CartItem, CartItemModifier
from app.modules.cart.schemas import (
    MAX_CART_LINES,
    MAX_LINE_QUANTITY,
    CartIssueOut,
    CartItemCreate,
    CartItemOut,
    CartItemUpdate,
    CartModifierOut,
    CartOut,
)
from app.modules.pricing.service import ZERO, evaluate_line, load_catalog, selection_error

LineKey = tuple[uuid.UUID, uuid.UUID, frozenset[tuple[uuid.UUID, int]], str | None]


def _not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def _limit_error(field: str, message: str) -> AppError:
    return AppError(
        422, "VALIDATION_ERROR", "Проверьте данные", details=[{"field": field, "message": message}]
    )


def _quantity_limit() -> AppError:
    return _limit_error("quantity", f"в одной позиции не более {MAX_LINE_QUANTITY} шт. (DEC-146)")


async def _lock_cart(
    session: AsyncSession, user_id: uuid.UUID, *, create: bool
) -> uuid.UUID | None:
    """Lock (and optionally create) the user's cart row; its id or None."""
    if create:
        await session.execute(
            pg_insert(Cart)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
    return await session.scalar(select(Cart.id).where(Cart.user_id == user_id).with_for_update())


async def _touch(session: AsyncSession, cart_id: uuid.UUID) -> None:
    await session.execute(update(Cart).where(Cart.id == cart_id).values(updated_at=func.now()))


async def _line_modifiers(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    result: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
    if item_ids:
        for item_id, modifier_id, quantity in await session.execute(
            select(
                CartItemModifier.cart_item_id,
                CartItemModifier.modifier_id,
                CartItemModifier.quantity,
            ).where(CartItemModifier.cart_item_id.in_(item_ids))
        ):
            result[item_id][modifier_id] = quantity
    return result


def _key(
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    modifiers: Mapping[uuid.UUID, int],
    instructions: str | None,
) -> LineKey:
    return (product_id, variant_id, frozenset(modifiers.items()), instructions)


async def _lines(session: AsyncSession, cart_id: uuid.UUID) -> list[CartItem]:
    return list(
        (
            await session.scalars(
                select(CartItem)
                .where(CartItem.cart_id == cart_id)
                .order_by(CartItem.created_at, CartItem.id)
            )
        ).all()
    )


# --------------------------------------------------------------------------
# Shared with checkout (stage 6)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CartLine:
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    quantity: int
    special_instructions: str | None
    modifiers: dict[uuid.UUID, int]


@dataclass(frozen=True)
class CartContent:
    cart_id: uuid.UUID | None
    lines: list[CartLine]


async def load_cart_content(
    session: AsyncSession, user_id: uuid.UUID, *, lock: bool
) -> CartContent:
    """Lines of the user's cart in display order; with `lock` the cart row is
    locked (`FOR UPDATE`) for the rest of the transaction (§14.1 step 2)."""
    if lock:
        cart_id = await _lock_cart(session, user_id, create=False)
    else:
        cart_id = await session.scalar(select(Cart.id).where(Cart.user_id == user_id))
    lines = await _lines(session, cart_id) if cart_id else []
    modifiers = await _line_modifiers(session, [line.id for line in lines])
    return CartContent(
        cart_id=cart_id,
        lines=[
            CartLine(
                id=line.id,
                product_id=line.product_id,
                variant_id=line.variant_id,
                quantity=line.quantity,
                special_instructions=line.special_instructions,
                modifiers=dict(modifiers.get(line.id, {})),
            )
            for line in lines
        ],
    )


async def empty_cart(session: AsyncSession, cart_id: uuid.UUID) -> None:
    """Remove all lines; the cart row stays and is reused (§6.1). No commit."""
    await session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
    await _touch(session, cart_id)


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------


async def get_cart(session: AsyncSession, user_id: uuid.UUID, chain: tuple[str, ...]) -> CartOut:
    cart_id = await session.scalar(select(Cart.id).where(Cart.user_id == user_id))
    lines = await _lines(session, cart_id) if cart_id else []
    modifiers = await _line_modifiers(session, [line.id for line in lines])
    catalog = await load_catalog(
        session,
        (line.product_id for line in lines),
        (m for selection in modifiers.values() for m in selection),
        chain,
    )

    items: list[CartItemOut] = []
    subtotal = ZERO
    for line in lines:
        evaluation = evaluate_line(
            catalog, line.product_id, line.variant_id, modifiers.get(line.id, {})
        )
        product = catalog.products.get(line.product_id)
        variant = catalog.variants.get(line.variant_id)
        line_total = evaluation.line_total(line.quantity)
        if evaluation.is_valid and line_total is not None:
            subtotal += line_total
        items.append(
            CartItemOut(
                id=line.id,
                product_id=line.product_id,
                variant_id=line.variant_id,
                product_name=product.name if product else "",
                variant_name=variant.name if variant else "",
                image_url=product.image_url if product else None,
                quantity=line.quantity,
                special_instructions=line.special_instructions,
                modifiers=[
                    CartModifierOut(
                        id=m.modifier_id,
                        group_id=m.group_id,
                        group_name=m.group_name,
                        name=m.name,
                        quantity=m.quantity,
                        unit_price=m.unit_price,
                    )
                    for m in evaluation.modifiers
                ],
                unit_price=evaluation.unit_price,
                line_total=line_total,
                is_available=evaluation.is_valid,
                issues=[CartIssueOut(**issue.as_dict()) for issue in evaluation.issues],
            )
        )
    return CartOut(
        items=items,
        items_count=sum(line.quantity for line in lines),
        subtotal=subtotal,
        has_issues=any(not item.is_available for item in items),
    )


# --------------------------------------------------------------------------
# Changes
# --------------------------------------------------------------------------


async def add_item(
    session: AsyncSession, user_id: uuid.UUID, payload: CartItemCreate, chain: tuple[str, ...]
) -> CartOut:
    selection = {choice.id: choice.quantity for choice in payload.modifiers}
    cart_id = await _lock_cart(session, user_id, create=True)
    assert cart_id is not None  # noqa: S101 - created above

    catalog = await load_catalog(session, [payload.product_id], selection.keys(), chain)
    evaluation = evaluate_line(catalog, payload.product_id, payload.variant_id, selection)
    if not evaluation.is_valid:
        raise selection_error(evaluation.issues)

    lines = await _lines(session, cart_id)
    modifiers = await _line_modifiers(session, [line.id for line in lines])
    wanted = _key(payload.product_id, payload.variant_id, selection, payload.special_instructions)
    same = next(
        (
            line
            for line in lines
            if _key(
                line.product_id,
                line.variant_id,
                modifiers.get(line.id, {}),
                line.special_instructions,
            )
            == wanted
        ),
        None,
    )
    if same is not None:
        if same.quantity + payload.quantity > MAX_LINE_QUANTITY:
            raise _quantity_limit()
        same.quantity += payload.quantity
    else:
        if len(lines) >= MAX_CART_LINES:
            raise _limit_error("cart", f"в корзине не более {MAX_CART_LINES} позиций (DEC-146)")
        item_id = await session.scalar(
            insert(CartItem)
            .values(
                cart_id=cart_id,
                product_id=payload.product_id,
                variant_id=payload.variant_id,
                quantity=payload.quantity,
                special_instructions=payload.special_instructions,
            )
            .returning(CartItem.id)
        )
        if selection:
            await session.execute(
                insert(CartItemModifier),
                [
                    {"cart_item_id": item_id, "modifier_id": modifier_id, "quantity": quantity}
                    for modifier_id, quantity in selection.items()
                ],
            )
    await _touch(session, cart_id)
    await session.commit()
    return await get_cart(session, user_id, chain)


async def update_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: CartItemUpdate,
    chain: tuple[str, ...],
) -> CartOut:
    cart_id = await _lock_cart(session, user_id, create=False)
    lines = await _lines(session, cart_id) if cart_id else []
    line = next((candidate for candidate in lines if candidate.id == item_id), None)
    if cart_id is None or line is None:
        # Another user's line is indistinguishable from a missing one.
        raise _not_found()

    if "quantity" in payload.model_fields_set and payload.quantity is not None:
        line.quantity = payload.quantity
    if "special_instructions" in payload.model_fields_set:
        line.special_instructions = payload.special_instructions

    # DEC-12: if the changed line now equals another line, they are merged.
    modifiers = await _line_modifiers(session, [candidate.id for candidate in lines])
    key = _key(
        line.product_id, line.variant_id, modifiers.get(line.id, {}), line.special_instructions
    )
    twin = next(
        (
            other
            for other in lines
            if other.id != line.id
            and _key(
                other.product_id,
                other.variant_id,
                modifiers.get(other.id, {}),
                other.special_instructions,
            )
            == key
        ),
        None,
    )
    if twin is not None:
        if twin.quantity + line.quantity > MAX_LINE_QUANTITY:
            raise _quantity_limit()
        twin.quantity += line.quantity
        await session.flush()
        await session.execute(delete(CartItem).where(CartItem.id == line.id))
    await _touch(session, cart_id)
    await session.commit()
    return await get_cart(session, user_id, chain)


async def delete_item(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    cart_id = await _lock_cart(session, user_id, create=False)
    deleted = (
        await session.execute(
            delete(CartItem)
            .where(CartItem.id == item_id, CartItem.cart_id == cart_id)
            .returning(CartItem.id)
        )
        if cart_id
        else None
    )
    if deleted is None or deleted.scalar_one_or_none() is None:
        await session.rollback()
        raise _not_found()
    await _touch(session, cart_id)
    await session.commit()


async def clear_cart(session: AsyncSession, user_id: uuid.UUID) -> None:
    cart_id = await _lock_cart(session, user_id, create=False)
    if cart_id is not None:
        await session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
        await _touch(session, cart_id)
    await session.commit()
