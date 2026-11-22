"""The courier's own profile, assignments and actions (API §10; DATABASE_SCHEMA.md
§7.1, §9.3; DEC-36, DEC-43, DEC-83, DEC-92, DEC-106, DEC-151).

Every action works only on the courier's own assignment; any other order is
indistinguishable from a missing one (404). The courier id comes from the
access token only. Locks (DEC-151 п. 6): the order row first (`FOR UPDATE`),
then the assignment row; `users` and `courier_profiles` are not locked by
the actions. Availability locks only the profile row.

Repeats (DEC-151 п. 4): `accept` of an accepted assignment and `delivered`
or `decline` of an already completed / declined own assignment return 200
without changes; a repeated `picked-up` is `409 INVALID_STATUS_TRANSITION`.
"""

import math
import uuid
from collections import defaultdict

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.addresses.schemas import Pagination
from app.modules.courier.assignments import active_count, invalid_status, not_found
from app.modules.courier.schemas import (
    AvailabilityIn,
    CourierActiveList,
    CourierAddress,
    CourierHistoryList,
    CourierHistoryOut,
    CourierItem,
    CourierItemModifier,
    CourierMe,
    CourierOrderOut,
    DeclineIn,
)
from app.modules.delivery.enums import AssignmentStatus
from app.modules.delivery.models import CourierAssignment, Delivery
from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import Order, OrderItem, OrderItemModifier
from app.modules.orders.status import Actor, change_status
from app.modules.payments.enums import PaymentMethodCode
from app.modules.users.models import CourierProfile, User

# Before these statuses the courier may still accept (DEC-83).
BEFORE_DEPARTURE = (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP)


def _forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", "Доступ запрещён")


def _already_accepted() -> AppError:
    return AppError(409, "ASSIGNMENT_ALREADY_ACCEPTED", "Назначение уже принято")


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


async def me(session: AsyncSession, user_id: uuid.UUID) -> CourierMe:
    row = (
        await session.execute(
            select(
                User.id,
                User.full_name,
                CourierProfile.is_available,
                CourierProfile.max_active_orders,
                active_count(User.id).label("active"),
            )
            .join(CourierProfile, CourierProfile.user_id == User.id)
            .where(User.id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise _forbidden()  # the courier role without a profile (DEC-27)
    return CourierMe(
        user_id=row.id,
        full_name=row.full_name,
        is_available=row.is_available,
        max_active_orders=row.max_active_orders,
        active_assignments=int(row.active),
    )


async def set_availability(
    session: AsyncSession, user_id: uuid.UUID, payload: AvailabilityIn
) -> CourierMe:
    locked = await session.scalar(
        select(CourierProfile.user_id).where(CourierProfile.user_id == user_id).with_for_update()
    )
    if locked is None:
        raise _forbidden()
    await session.execute(
        update(CourierProfile)
        .where(CourierProfile.user_id == user_id)
        .values(is_available=payload.is_available)
    )
    await session.commit()
    return await me(session, user_id)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


async def _items(
    session: AsyncSession, order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CourierItem]]:
    result: dict[uuid.UUID, list[CourierItem]] = defaultdict(list)
    if not order_ids:
        return result
    rows = (
        await session.execute(
            select(
                OrderItem.id,
                OrderItem.order_id,
                OrderItem.product_name,
                OrderItem.variant_name,
                OrderItem.quantity,
                OrderItem.special_instructions,
            )
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.product_name, OrderItem.variant_name, OrderItem.id)
        )
    ).all()
    modifiers: dict[uuid.UUID, list[CourierItemModifier]] = defaultdict(list)
    if rows:
        for m in await session.execute(
            select(
                OrderItemModifier.order_item_id,
                OrderItemModifier.group_name,
                OrderItemModifier.modifier_name,
                OrderItemModifier.quantity,
            )
            .where(OrderItemModifier.order_item_id.in_([r.id for r in rows]))
            .order_by(OrderItemModifier.id)
        ):
            modifiers[m.order_item_id].append(
                CourierItemModifier(
                    group_name=m.group_name, modifier_name=m.modifier_name, quantity=m.quantity
                )
            )
    for r in rows:
        result[r.order_id].append(
            CourierItem(
                product_name=r.product_name,
                variant_name=r.variant_name,
                quantity=r.quantity,
                special_instructions=r.special_instructions,
                modifiers=modifiers.get(r.id, []),
            )
        )
    return result


async def _active_orders(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID | None = None
) -> list[CourierOrderOut]:
    query = (
        select(Order, CourierAssignment, Delivery.delivery_comment)
        .join(CourierAssignment, CourierAssignment.order_id == Order.id)
        .outerjoin(Delivery, Delivery.order_id == Order.id)
        .where(
            CourierAssignment.courier_id == courier_id,
            CourierAssignment.status == AssignmentStatus.ACTIVE,
        )
        .order_by(CourierAssignment.assigned_at, CourierAssignment.id)
    )
    if order_id is not None:
        query = query.where(Order.id == order_id)
    rows = (await session.execute(query)).all()
    items = await _items(session, [order.id for order, _, _ in rows])
    result = []
    for order, assignment, delivery_comment in rows:
        accepted = assignment.accepted_at is not None
        address = None
        if order.delivery_address_text is not None:
            assert order.delivery_latitude is not None  # noqa: S101 - snapshot invariant
            assert order.delivery_longitude is not None  # noqa: S101
            address = CourierAddress(
                address_text=order.delivery_address_text,
                latitude=order.delivery_latitude,
                longitude=order.delivery_longitude,
                entrance=order.delivery_entrance,
                floor=order.delivery_floor,
                apartment=order.delivery_apartment,
                comment=delivery_comment,
            )
        is_cash = order.payment_method_code == PaymentMethodCode.CASH
        result.append(
            CourierOrderOut(
                assignment_id=assignment.id,
                order_id=order.id,
                order_number=order.order_number,
                status=order.status,
                created_at=order.created_at,
                assigned_at=assignment.assigned_at,
                accepted_at=assignment.accepted_at,
                address=address,
                customer_name=order.customer_name,
                customer_phone=order.customer_phone,
                customer_comment=order.customer_comment,
                items=items.get(order.id, []),
                payment_method_code=order.payment_method_code,
                total_amount=order.total_amount,
                currency=order.currency,
                amount_to_collect=order.total_amount if is_cash else None,
                can_accept=not accepted and order.status in BEFORE_DEPARTURE,
                can_decline=not accepted and order.status in BEFORE_DEPARTURE,
                can_pick_up=accepted and order.status == OrderStatus.READY_FOR_PICKUP,
                can_deliver=order.status == OrderStatus.OUT_FOR_DELIVERY,
            )
        )
    return result


async def active_orders(session: AsyncSession, courier_id: uuid.UUID) -> CourierActiveList:
    return CourierActiveList(items=await _active_orders(session, courier_id))


async def order_detail(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID
) -> CourierOrderOut:
    """Only an active own assignment; after reassignment, cancellation,
    completion or decline the details are no longer shown (DEC-106)."""
    found = await _active_orders(session, courier_id, order_id)
    if not found:
        raise not_found()
    return found[0]


_FINISHED = (AssignmentStatus.COMPLETED, AssignmentStatus.DECLINED)


def _history_query(courier_id: uuid.UUID):  # noqa: ANN202 - Select
    return (
        select(
            CourierAssignment.id,
            CourierAssignment.status,
            func.coalesce(CourierAssignment.completed_at, CourierAssignment.declined_at).label(
                "finished_at"
            ),
            Order.id.label("order_id"),
            Order.order_number,
            Order.total_amount,
            Order.currency,
            Order.payment_method_code,
        )
        .join(Order, Order.id == CourierAssignment.order_id)
        .where(
            CourierAssignment.courier_id == courier_id,
            CourierAssignment.status.in_(_FINISHED),
        )
    )


def _history_out(row) -> CourierHistoryOut:  # noqa: ANN001 - Row
    return CourierHistoryOut(
        assignment_id=row.id,
        order_id=row.order_id,
        order_number=row.order_number,
        assignment_status=row.status,
        finished_at=row.finished_at,
        total_amount=row.total_amount,
        currency=row.currency,
        payment_method_code=row.payment_method_code,
    )


async def history(
    session: AsyncSession, courier_id: uuid.UUID, *, page: int, page_size: int
) -> CourierHistoryList:
    """Completed and declined assignments: no address or contacts (DEC-106)."""
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(CourierAssignment)
            .where(
                CourierAssignment.courier_id == courier_id,
                CourierAssignment.status.in_(_FINISHED),
            )
        )
        or 0
    )
    query = _history_query(courier_id)
    rows = await session.execute(
        query.order_by(
            func.coalesce(CourierAssignment.completed_at, CourierAssignment.declined_at).desc(),
            CourierAssignment.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return CourierHistoryList(
        items=[_history_out(row) for row in rows],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def _finished(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID, status: AssignmentStatus
) -> CourierHistoryOut | None:
    row = (
        await session.execute(
            _history_query(courier_id)
            .where(Order.id == order_id, CourierAssignment.status == status)
            .order_by(CourierAssignment.assigned_at.desc(), CourierAssignment.id.desc())
            .limit(1)
        )
    ).one_or_none()
    return _history_out(row) if row else None


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


async def _lock(session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID):  # noqa: ANN202
    """Lock the order row, then the courier's active assignment (DEC-151 п. 6).

    Returns (order status, assignment row or None)."""
    status = await session.scalar(
        select(Order.status).where(Order.id == order_id).with_for_update()
    )
    if status is None:
        raise not_found()
    assignment = (
        await session.execute(
            select(CourierAssignment.id, CourierAssignment.accepted_at)
            .where(
                CourierAssignment.order_id == order_id,
                CourierAssignment.courier_id == courier_id,
                CourierAssignment.status == AssignmentStatus.ACTIVE,
            )
            .with_for_update()
        )
    ).one_or_none()
    return status, assignment


async def accept(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID
) -> CourierOrderOut:
    """DEC-52, DEC-83: `accepted_at`; the order status does not change."""
    status, assignment = await _lock(session, courier_id, order_id)
    if assignment is None:
        raise not_found()
    if assignment.accepted_at is not None:
        await session.rollback()  # DEC-151 п. 4: repeat, nothing changes
        return await order_detail(session, courier_id, order_id)
    if status not in BEFORE_DEPARTURE:
        raise invalid_status()
    await session.execute(
        update(CourierAssignment)
        .where(CourierAssignment.id == assignment.id)
        .values(accepted_at=func.now())
    )
    await session.commit()
    return await order_detail(session, courier_id, order_id)


async def decline(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID, payload: DeclineIn
) -> CourierHistoryOut:
    """DEC-92, DEC-151 п. 5: only before acceptance and before
    `out_for_delivery`; the order keeps its status."""
    status, assignment = await _lock(session, courier_id, order_id)
    if assignment is None:
        done = await _finished(session, courier_id, order_id, AssignmentStatus.DECLINED)
        if done is None:
            raise not_found()
        await session.rollback()  # DEC-151 п. 4: repeat of an own decline
        return done
    if assignment.accepted_at is not None:
        raise _already_accepted()
    if status not in BEFORE_DEPARTURE:
        raise invalid_status()  # e.g. out_for_delivery after the override (DEC-91)
    await session.execute(
        update(CourierAssignment)
        .where(CourierAssignment.id == assignment.id)
        .values(
            status=AssignmentStatus.DECLINED.value,
            declined_at=func.now(),
            decline_reason=payload.reason,
        )
    )
    await session.commit()
    done = await _finished(session, courier_id, order_id, AssignmentStatus.DECLINED)
    assert done is not None  # noqa: S101 - written above
    return done


async def picked_up(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID
) -> CourierOrderOut:
    """`ready_for_pickup → out_for_delivery` (DEC-36, DEC-83)."""
    _, assignment = await _lock(session, courier_id, order_id)
    if assignment is None:
        raise not_found()
    await change_status(
        session, order_id, OrderStatus.OUT_FOR_DELIVERY.value, Actor.COURIER, actor_id=courier_id
    )
    await session.commit()
    return await order_detail(session, courier_id, order_id)


async def delivered(
    session: AsyncSession, courier_id: uuid.UUID, order_id: uuid.UUID
) -> CourierHistoryOut:
    """`out_for_delivery → completed`: `delivered_at`, the assignment
    `completed`, cash `succeeded` (DEC-43), in one transaction."""
    status, assignment = await _lock(session, courier_id, order_id)
    if assignment is None:
        done = await _finished(session, courier_id, order_id, AssignmentStatus.COMPLETED)
        if done is None or status != OrderStatus.COMPLETED:
            raise not_found()
        await session.rollback()  # DEC-151 п. 4: repeat, no side effects
        return done
    await change_status(
        session, order_id, OrderStatus.COMPLETED.value, Actor.COURIER, actor_id=courier_id
    )
    await session.commit()
    done = await _finished(session, courier_id, order_id, AssignmentStatus.COMPLETED)
    assert done is not None  # noqa: S101 - completed by change_status
    return done


__all__ = [
    "accept",
    "active_orders",
    "decline",
    "delivered",
    "history",
    "me",
    "order_detail",
    "picked_up",
    "set_availability",
]
