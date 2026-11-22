"""Single cancellation operation (DATABASE_SCHEMA.md §14.3; DEC-39…DEC-41,
DEC-82, DEC-98, DEC-132, DEC-149).

One transaction (the caller's), no commit:
1. lock the order; already `cancelled` -> current state, no side effects;
2. the transition must be allowed by the state machine (§7.1) for the actor;
3. `status = cancelled`, `cancelled_at`, `cancellation_reason_code`, history
   row with the reason as comment;
4. payments: a successful mock payment -> `refunded` (`refunded_at`, only a
   simulation), every `pending` attempt -> `cancelled`;
5. the active courier assignment -> `cancelled`;
6. a pending cancellation request -> `approved`;
7. domain event `OrderStatusChanged` (DEC-79).

Stage 7 calls it only from the payment timeout (system); staff actions use it
in stages 8–9.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.delivery.enums import AssignmentStatus
from app.modules.delivery.models import CourierAssignment
from app.modules.orders.enums import CancellationRequestStatus, OrderStatus
from app.modules.orders.events import OrderStatusChanged, publish
from app.modules.orders.models import CancellationRequest, Order, OrderStatusHistory
from app.modules.orders.status import Actor, OrderState, check_transition, load_context
from app.modules.payments.enums import PaymentStatus
from app.modules.payments.models import Payment


@dataclass(frozen=True)
class CancelResult:
    order_id: uuid.UUID
    # False when the order was already cancelled (idempotent repeat).
    changed: bool


async def cancel_order(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    reason_code: str,
    comment: str,
    actor: Actor,
    actor_id: uuid.UUID | None,
) -> CancelResult:
    order = (
        await session.execute(
            select(Order.status, Order.delivery_type, Order.payment_method_code, Order.user_id)
            .where(Order.id == order_id)
            .with_for_update()
        )
    ).one_or_none()
    if order is None:
        raise AppError(404, "NOT_FOUND", "Ресурс не найден")
    if order.status == OrderStatus.CANCELLED:
        return CancelResult(order_id, changed=False)

    plan = check_transition(
        OrderState(order.status, order.delivery_type, order.payment_method_code),
        OrderStatus.CANCELLED.value,
        actor,
        actor_id=actor_id,
        comment=comment,
        context=await load_context(session, order_id),
    )
    now = await session.scalar(select(func.now()))
    await session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(
            status=OrderStatus.CANCELLED.value,
            cancelled_at=now,
            cancellation_reason_code=reason_code,
        )
    )
    created_at = await session.scalar(
        insert(OrderStatusHistory)
        .values(
            order_id=order_id,
            old_status=plan.old_status,
            new_status=OrderStatus.CANCELLED.value,
            changed_by=actor_id,
            comment=comment.strip(),
        )
        .returning(OrderStatusHistory.created_at)
    )

    # Payments (§8.2): refund a simulated success, cancel unfinished attempts.
    await session.execute(
        update(Payment)
        .where(
            Payment.order_id == order_id,
            Payment.status == PaymentStatus.SUCCEEDED,
            Payment.is_simulated,
        )
        .values(status=PaymentStatus.REFUNDED.value, refunded_at=now)
    )
    await session.execute(
        update(Payment)
        .where(Payment.order_id == order_id, Payment.status == PaymentStatus.PENDING)
        .values(status=PaymentStatus.CANCELLED.value)
    )
    await session.execute(
        update(CourierAssignment)
        .where(
            CourierAssignment.order_id == order_id,
            CourierAssignment.status == AssignmentStatus.ACTIVE,
        )
        .values(status=AssignmentStatus.CANCELLED.value)
    )
    await session.execute(
        update(CancellationRequest)
        .where(
            CancellationRequest.order_id == order_id,
            CancellationRequest.status == CancellationRequestStatus.PENDING,
        )
        .values(
            status=CancellationRequestStatus.APPROVED.value,
            reviewed_by=actor_id,
            reviewed_at=now,
        )
    )
    await publish(
        session,
        OrderStatusChanged(
            order_id=order_id,
            customer_id=order.user_id,
            old_status=plan.old_status,
            new_status=OrderStatus.CANCELLED.value,
            changed_by=actor_id,
            occurred_at=created_at or datetime.now(UTC),
        ),
    )
    return CancelResult(order_id, changed=True)
