"""Customer views of orders (API §6.3, DEC-25, DEC-38, DEC-42, DEC-148).

Only the owner sees an order; another user's order is indistinguishable
from a missing one (404). Everything shown comes from the order snapshots,
never from the current catalog (§14.4). History comments are shown only
for `rejected`/`cancelled`, where they are the reason (DEC-98, DEC-132);
staff fields (`changed_by`, `is_admin_override`) are not exposed.
"""

import math
import uuid
from collections import defaultdict

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.addresses.schemas import Pagination
from app.modules.delivery.models import Delivery
from app.modules.orders.enums import CancellationRequestStatus, OrderStatus
from app.modules.orders.models import (
    CancellationRequest,
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
)
from app.modules.orders.schemas import (
    CancellationRequestOut,
    OrderAddressOut,
    OrderDetail,
    OrderItemModifierOut,
    OrderItemOut,
    OrderList,
    OrderSummary,
    PaymentOut,
    StatusHistoryOut,
)
from app.modules.orders.status import COMMENT_REQUIRED
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.payments.service import summary_status

# DEC-38: a customer may ask for cancellation only in these statuses.
CANCELLATION_REQUEST_STATUSES = frozenset(
    {OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PREPARING}
)


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


async def list_orders(
    session: AsyncSession, user_id: uuid.UUID, *, page: int, page_size: int
) -> OrderList:
    total = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.user_id == user_id)
        )
        or 0
    )
    counts = (
        select(OrderItem.order_id, func.sum(OrderItem.quantity).label("items_count"))
        .group_by(OrderItem.order_id)
        .subquery()
    )
    rows = await session.execute(
        select(
            Order.id,
            Order.order_number,
            Order.status,
            Order.delivery_type,
            Order.payment_method_code,
            Order.total_amount,
            Order.currency,
            Order.created_at,
            func.coalesce(counts.c.items_count, 0).label("items_count"),
        )
        .outerjoin(counts, counts.c.order_id == Order.id)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return OrderList(
        items=[
            OrderSummary(
                id=row.id,
                order_number=row.order_number,
                status=row.status,
                delivery_type=row.delivery_type,
                payment_method_code=row.payment_method_code,
                total_amount=row.total_amount,
                currency=row.currency,
                items_count=int(row.items_count),
                created_at=row.created_at,
            )
            for row in rows
        ],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def has_pending_request(session: AsyncSession, order_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    CancellationRequest.order_id == order_id,
                    CancellationRequest.status == CancellationRequestStatus.PENDING,
                )
            )
        )
    )


async def get_order(session: AsyncSession, user_id: uuid.UUID, order_id: uuid.UUID) -> OrderDetail:
    """The order of its owner only (DEC-25)."""
    return await load_order_detail(session, order_id, owner_id=user_id)


async def load_order_detail(
    session: AsyncSession, order_id: uuid.UUID, *, owner_id: uuid.UUID | None
) -> OrderDetail:
    """Snapshot view of an order; `owner_id=None` only for staff services
    that checked the role themselves (DEC-150)."""
    query = select(Order).where(Order.id == order_id)
    if owner_id is not None:
        query = query.where(Order.user_id == owner_id)
    order = await session.scalar(query)
    if order is None:
        raise not_found()

    items = list(
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            # order_items has no position column: a stable, readable order.
            .order_by(OrderItem.product_name, OrderItem.variant_name, OrderItem.id)
        )
    )
    modifiers: dict[uuid.UUID, list[OrderItemModifierOut]] = defaultdict(list)
    if items:
        for row in await session.scalars(
            select(OrderItemModifier)
            .where(OrderItemModifier.order_item_id.in_([item.id for item in items]))
            .order_by(OrderItemModifier.id)
        ):
            modifiers[row.order_item_id].append(
                OrderItemModifierOut(
                    group_name=row.group_name,
                    modifier_name=row.modifier_name,
                    quantity=row.quantity,
                    unit_price=row.unit_price,
                    total_price=row.total_price,
                )
            )

    delivery_comment = await session.scalar(
        select(Delivery.delivery_comment).where(Delivery.order_id == order_id)
    )
    payments = [
        PaymentOut(
            id=row.id,
            method_code=row.code,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            is_simulated=row.is_simulated,
            transaction_reference=row.transaction_reference,
            created_at=row.created_at,
            paid_at=row.paid_at,
            refunded_at=row.refunded_at,
        )
        for row in await session.execute(
            select(
                Payment.id,
                PaymentMethod.code,
                Payment.amount,
                Payment.currency,
                Payment.status,
                Payment.is_simulated,
                Payment.transaction_reference,
                Payment.created_at,
                Payment.paid_at,
                Payment.refunded_at,
            )
            .join(PaymentMethod, PaymentMethod.id == Payment.payment_method_id)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at, Payment.id)
        )
    ]
    history = [
        StatusHistoryOut(
            old_status=row.old_status,
            new_status=row.new_status,
            comment=row.comment if row.new_status in COMMENT_REQUIRED else None,
            created_at=row.created_at,
        )
        for row in await session.scalars(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
        )
    ]
    requests = [
        CancellationRequestOut(
            id=row.id,
            reason=row.reason,
            status=row.status,
            admin_comment=row.admin_comment,
            created_at=row.created_at,
            reviewed_at=row.reviewed_at,
        )
        for row in await session.scalars(
            select(CancellationRequest)
            .where(CancellationRequest.order_id == order_id)
            .order_by(CancellationRequest.created_at, CancellationRequest.id)
        )
    ]
    pending_request = any(r.status == CancellationRequestStatus.PENDING for r in requests)

    address = None
    if order.delivery_address_text is not None:
        assert order.delivery_latitude is not None and order.delivery_longitude is not None  # noqa: S101
        address = OrderAddressOut(
            address_text=order.delivery_address_text,
            latitude=order.delivery_latitude,
            longitude=order.delivery_longitude,
            entrance=order.delivery_entrance,
            floor=order.delivery_floor,
            apartment=order.delivery_apartment,
            comment=delivery_comment,
        )

    return OrderDetail(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        language_code=order.language_code,
        delivery_type=order.delivery_type,
        payment_method_code=order.payment_method_code,
        payment_status=summary_status([p.status for p in payments]),
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        currency=order.currency,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        customer_comment=order.customer_comment,
        address=address,
        payment_due_at=order.payment_due_at,
        cancellation_reason_code=order.cancellation_reason_code,
        cancelled_at=order.cancelled_at,
        completed_at=order.completed_at,
        created_at=order.created_at,
        items=[
            OrderItemOut(
                id=item.id,
                product_id=item.product_id,
                product_name=item.product_name,
                variant_name=item.variant_name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                total_price=item.total_price,
                special_instructions=item.special_instructions,
                modifiers=modifiers.get(item.id, []),
            )
            for item in items
        ],
        payments=payments,
        status_history=history,
        cancellation_requests=requests,
        can_request_cancellation=(
            order.status in CANCELLATION_REQUEST_STATUSES and not pending_request
        ),
    )
