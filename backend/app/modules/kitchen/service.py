"""Kitchen queue and its two actions (API §9 "Kitchen"; DEC-35, DEC-106, DEC-150).

The queue holds `confirmed`, `preparing` and `ready_for_pickup` orders,
earliest confirmation first. Unpaid mock_card orders cannot be confirmed
(DEC-45), so they never appear here. Actions use the existing state machine:
`confirmed → preparing` and `preparing → ready_for_pickup` (cook or admin).
"""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kitchen.schemas import (
    KitchenItemOut,
    KitchenModifierOut,
    KitchenOrderOut,
    KitchenQueue,
)
from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import Order, OrderItem, OrderItemModifier, OrderStatusHistory
from app.modules.orders.status import Actor, change_status

QUEUE_STATUSES = (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP)


def _reached(status: OrderStatus):  # noqa: ANN202 - scalar subquery
    """Time the order first entered `status` (from the history)."""
    return (
        select(func.min(OrderStatusHistory.created_at))
        .where(
            OrderStatusHistory.order_id == Order.id,
            OrderStatusHistory.new_status == status,
        )
        .correlate(Order)
        .scalar_subquery()
    )


async def _orders(
    session: AsyncSession, order_ids: list[uuid.UUID] | None
) -> list[KitchenOrderOut]:
    confirmed_at = _reached(OrderStatus.CONFIRMED).label("confirmed_at")
    preparing_at = _reached(OrderStatus.PREPARING).label("preparing_at")
    query = select(
        Order.id,
        Order.order_number,
        Order.delivery_type,
        Order.status,
        confirmed_at,
        preparing_at,
    )
    if order_ids is None:
        query = query.where(Order.status.in_(QUEUE_STATUSES)).order_by(
            confirmed_at.asc().nulls_last(), Order.created_at, Order.id
        )
    else:
        query = query.where(Order.id.in_(order_ids))
    rows = (await session.execute(query)).all()
    ids = [row.id for row in rows]

    items: dict[uuid.UUID, list[tuple[uuid.UUID, KitchenItemOut]]] = defaultdict(list)
    modifiers: dict[uuid.UUID, list[KitchenModifierOut]] = defaultdict(list)
    if ids:
        item_rows = (
            await session.execute(
                select(
                    OrderItem.id,
                    OrderItem.order_id,
                    OrderItem.product_name,
                    OrderItem.variant_name,
                    OrderItem.quantity,
                    OrderItem.special_instructions,
                )
                .where(OrderItem.order_id.in_(ids))
                .order_by(OrderItem.product_name, OrderItem.variant_name, OrderItem.id)
            )
        ).all()
        for row in await session.execute(
            select(
                OrderItemModifier.order_item_id,
                OrderItemModifier.group_name,
                OrderItemModifier.modifier_name,
                OrderItemModifier.quantity,
            )
            .where(OrderItemModifier.order_item_id.in_([r.id for r in item_rows]))
            .order_by(OrderItemModifier.id)
        ):
            modifiers[row.order_item_id].append(
                KitchenModifierOut(
                    group_name=row.group_name,
                    modifier_name=row.modifier_name,
                    quantity=row.quantity,
                )
            )
        for row in item_rows:
            items[row.order_id].append(
                (
                    row.id,
                    KitchenItemOut(
                        product_name=row.product_name,
                        variant_name=row.variant_name,
                        quantity=row.quantity,
                        special_instructions=row.special_instructions,
                        modifiers=[],
                    ),
                )
            )
    result = []
    for row in rows:
        order_items = [
            item.model_copy(update={"modifiers": modifiers.get(item_id, [])})
            for item_id, item in items.get(row.id, [])
        ]
        result.append(
            KitchenOrderOut(
                id=row.id,
                order_number=row.order_number,
                delivery_type=row.delivery_type,
                status=row.status,
                confirmed_at=row.confirmed_at,
                preparing_started_at=row.preparing_at,
                items=order_items,
            )
        )
    return result


async def queue(session: AsyncSession) -> KitchenQueue:
    return KitchenQueue(items=await _orders(session, None))


async def act(
    session: AsyncSession,
    order_id: uuid.UUID,
    new_status: str,
    *,
    user_id: uuid.UUID,
    roles: frozenset[str],
) -> KitchenOrderOut:
    """`start` / `ready`; the actor is the cook if the user has that role."""
    actor = Actor.COOK if "cook" in roles else Actor.ADMIN
    await change_status(session, order_id, new_status, actor, actor_id=user_id)
    await session.commit()
    [order] = await _orders(session, [order_id])
    return order
