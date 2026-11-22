"""Order state machine (DATABASE_SCHEMA.md §7.1, §14.3; DEC-30…DEC-37, DEC-45,
DEC-79, DEC-83, DEC-91, DEC-132, DEC-148).

`check_transition` is a pure function: it decides from the order state and
a small context whether `actor` may move the order to `new_status`.
`change_status` locks the order row, re-reads the context, checks, writes
`orders.status` and `order_status_history` and publishes the domain event,
all in the caller's transaction.

Scope (DEC-148…DEC-151): cancellations go through the single operation of
§14.3 (`app.modules.orders.cancel`). All other transitions are applied here,
including `rejected` (payments by DEC-100, a pending cancellation request is
closed, DEC-101), the completion of a pickup order and the courier
transitions of a delivery (DEC-36, DEC-83) with the administrator override
(DEC-91). Completing an order sets `completed_at` and turns the cash payment
into `succeeded` (DEC-43); completing a delivery also sets
`deliveries.delivered_at` and completes the active assignment (§9.3).

Locks (DEC-151 п. 6): only the order row is locked here (`FOR UPDATE`); the
assignment, payment and delivery rows are updated after it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.delivery.enums import AssignmentStatus
from app.modules.delivery.models import CourierAssignment, Delivery
from app.modules.orders.enums import CancellationRequestStatus, DeliveryType, OrderStatus
from app.modules.orders.events import OrderStatusChanged, publish
from app.modules.orders.models import CancellationRequest, Order, OrderStatusHistory
from app.modules.payments.enums import PaymentMethodCode, PaymentStatus
from app.modules.payments.models import Payment


class Actor(StrEnum):
    ADMIN = "admin"
    COOK = "cook"
    COURIER = "courier"
    SYSTEM = "system"  # background jobs, e.g. the payment timeout (DEC-84)


S = OrderStatus
DELIVERY = DeliveryType.DELIVERY.value
PICKUP = DeliveryType.PICKUP.value


@dataclass(frozen=True)
class Rule:
    actor: Actor
    # None = both order types.
    delivery_type: str | None = None
    # Admin performs a courier transition (DEC-91): comment required,
    # history row marked `is_admin_override`.
    admin_override: bool = False


# (from, to) -> who may do it and for which order type (§7.1).
TRANSITIONS: dict[tuple[str, str], tuple[Rule, ...]] = {
    (S.PENDING, S.CONFIRMED): (Rule(Actor.ADMIN),),
    (S.PENDING, S.REJECTED): (Rule(Actor.ADMIN),),
    (S.CONFIRMED, S.PREPARING): (Rule(Actor.COOK), Rule(Actor.ADMIN)),
    (S.PREPARING, S.READY_FOR_PICKUP): (Rule(Actor.COOK), Rule(Actor.ADMIN)),
    (S.READY_FOR_PICKUP, S.OUT_FOR_DELIVERY): (
        Rule(Actor.COURIER, DELIVERY),
        Rule(Actor.ADMIN, DELIVERY, admin_override=True),
    ),
    (S.OUT_FOR_DELIVERY, S.COMPLETED): (
        Rule(Actor.COURIER, DELIVERY),
        Rule(Actor.ADMIN, DELIVERY, admin_override=True),
    ),
    (S.READY_FOR_PICKUP, S.COMPLETED): (Rule(Actor.ADMIN, PICKUP),),
    (S.PENDING, S.CANCELLED): (Rule(Actor.ADMIN), Rule(Actor.SYSTEM)),
    (S.CONFIRMED, S.CANCELLED): (Rule(Actor.ADMIN),),
    (S.PREPARING, S.CANCELLED): (Rule(Actor.ADMIN),),
    (S.READY_FOR_PICKUP, S.CANCELLED): (Rule(Actor.ADMIN),),
}

COMMENT_REQUIRED = frozenset({S.REJECTED, S.CANCELLED})  # DEC-132

# DEC-150 п. 7: the text of the automatic closing on a rejection (shown to the
# customer as the answer to his request).
REJECTED_REQUEST_COMMENT = "Заказ отклонён рестораном. Запрос отмены закрыт автоматически"
# DEC-101 for a completed order: the request can no longer be satisfied.
COMPLETED_REQUEST_COMMENT = "Заказ завершён. Запрос отмены закрыт автоматически"


@dataclass(frozen=True)
class OrderState:
    status: str
    delivery_type: str
    payment_method_code: str


@dataclass(frozen=True)
class TransitionContext:
    """Facts read from the database under the order lock."""

    has_succeeded_payment: bool = False
    # Courier of the active assignment and whether he accepted it.
    active_courier_id: uuid.UUID | None = None
    assignment_accepted: bool = False


@dataclass(frozen=True)
class TransitionPlan:
    old_status: str
    new_status: str
    is_admin_override: bool


def _invalid() -> AppError:
    return AppError(409, "INVALID_STATUS_TRANSITION", "Переход статуса не разрешён")


def _forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", "Доступ запрещён")


def _comment_required() -> AppError:
    return AppError(
        422,
        "VALIDATION_ERROR",
        "Проверьте данные",
        details=[{"field": "comment", "message": "обязательный комментарий"}],
    )


def check_transition(
    order: OrderState,
    new_status: str,
    actor: Actor,
    *,
    actor_id: uuid.UUID | None = None,
    comment: str | None = None,
    context: TransitionContext | None = None,
) -> TransitionPlan:
    """Raise if the transition is not allowed; otherwise describe it."""
    context = context or TransitionContext()
    rules = TRANSITIONS.get((order.status, new_status))
    if not rules:
        raise _invalid()
    by_type = [r for r in rules if r.delivery_type in (None, order.delivery_type)]
    if not by_type:
        raise _invalid()
    rule = next((r for r in by_type if r.actor == actor), None)
    if rule is None:
        raise _forbidden()

    has_comment = comment is not None and comment.strip() != ""
    if (new_status in COMMENT_REQUIRED or rule.admin_override) and not has_comment:
        raise _comment_required()

    # pending -> confirmed for mock_card only after a successful payment (DEC-45).
    if (
        (order.status, new_status) == (S.PENDING, S.CONFIRMED)
        and order.payment_method_code == PaymentMethodCode.MOCK_CARD
        and not context.has_succeeded_payment
    ):
        raise AppError(409, "PAYMENT_REQUIRED", "Заказ ещё не оплачен")

    # The system cancels only unpaid mock_card orders (DEC-84).
    if actor == Actor.SYSTEM and order.payment_method_code != PaymentMethodCode.MOCK_CARD:
        raise _forbidden()

    if (order.status, new_status) == (S.READY_FOR_PICKUP, S.OUT_FOR_DELIVERY):
        if context.active_courier_id is None:
            raise _invalid()  # an active assignment is required (DEC-36, DEC-91)
        if actor == Actor.COURIER:
            if context.active_courier_id != actor_id:
                raise _forbidden()
            if not context.assignment_accepted:
                raise AppError(409, "ASSIGNMENT_NOT_ACCEPTED", "Курьер не принял назначение")
    courier_completes = (order.status, new_status) == (S.OUT_FOR_DELIVERY, S.COMPLETED) and (
        actor == Actor.COURIER
    )
    if courier_completes and (
        context.active_courier_id is None or context.active_courier_id != actor_id
    ):
        raise _forbidden()

    return TransitionPlan(order.status, new_status, rule.admin_override)


class DeferredTransitionError(RuntimeError):
    """Cancellations must go through `cancel_order` (§14.3)."""


async def load_context(session: AsyncSession, order_id: uuid.UUID) -> TransitionContext:
    paid = await session.scalar(
        select(
            exists().where(Payment.order_id == order_id, Payment.status == PaymentStatus.SUCCEEDED)
        )
    )
    assignment = (
        await session.execute(
            select(CourierAssignment.courier_id, CourierAssignment.accepted_at).where(
                CourierAssignment.order_id == order_id,
                CourierAssignment.status == AssignmentStatus.ACTIVE,
            )
        )
    ).one_or_none()
    return TransitionContext(
        has_succeeded_payment=bool(paid),
        active_courier_id=assignment.courier_id if assignment else None,
        assignment_accepted=bool(assignment and assignment.accepted_at),
    )


async def _close_pending_request(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    comment: str,
    actor_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """DEC-101: the order reached a status where it can no longer be cancelled."""
    await session.execute(
        update(CancellationRequest)
        .where(
            CancellationRequest.order_id == order_id,
            CancellationRequest.status == CancellationRequestStatus.PENDING,
        )
        .values(
            status=CancellationRequestStatus.REJECTED.value,
            admin_comment=comment,
            reviewed_by=actor_id,
            reviewed_at=now,
        )
    )


async def _side_effects(
    session: AsyncSession,
    order_id: uuid.UUID,
    new_status: str,
    *,
    delivery_type: str,
    actor_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """Payments, deliveries, assignments and cancellation requests of a
    transition (§7.6, §8.2, §9.2, §9.3)."""
    if new_status == S.REJECTED:
        # DEC-100: the same payment rules as a cancellation.
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
        await _close_pending_request(
            session, order_id, comment=REJECTED_REQUEST_COMMENT, actor_id=actor_id, now=now
        )
    elif new_status == S.COMPLETED:
        # DEC-43: the cash payment succeeds together with the completion.
        await session.execute(
            update(Payment)
            .where(
                Payment.order_id == order_id,
                Payment.status == PaymentStatus.PENDING,
                ~Payment.is_simulated,
            )
            .values(status=PaymentStatus.SUCCEEDED.value, paid_at=now)
        )
        await _close_pending_request(
            session, order_id, comment=COMPLETED_REQUEST_COMMENT, actor_id=actor_id, now=now
        )
        if delivery_type == DELIVERY:
            # §9.2, §9.3: the courier (or the override, DEC-91) delivered it.
            await session.execute(
                update(Delivery).where(Delivery.order_id == order_id).values(delivered_at=now)
            )
            await session.execute(
                update(CourierAssignment)
                .where(
                    CourierAssignment.order_id == order_id,
                    CourierAssignment.status == AssignmentStatus.ACTIVE,
                )
                .values(status=AssignmentStatus.COMPLETED.value, completed_at=now)
            )


async def record_initial_status(
    session: AsyncSession, *, order_id: uuid.UUID, customer_id: uuid.UUID, changed_by: uuid.UUID
) -> None:
    """First history row of a new order (`pending`) and its event (§7.5)."""
    created_at = await session.scalar(
        insert(OrderStatusHistory)
        .values(
            order_id=order_id,
            old_status=None,
            new_status=S.PENDING.value,
            changed_by=changed_by,
        )
        .returning(OrderStatusHistory.created_at)
    )
    await publish(
        session,
        OrderStatusChanged(
            order_id=order_id,
            customer_id=customer_id,
            old_status=None,
            new_status=S.PENDING.value,
            changed_by=changed_by,
            occurred_at=created_at or datetime.now(UTC),
        ),
    )


async def change_status(
    session: AsyncSession,
    order_id: uuid.UUID,
    new_status: str,
    actor: Actor,
    *,
    actor_id: uuid.UUID | None,
    comment: str | None = None,
) -> TransitionPlan:
    """Lock the order, check and apply one transition (§14.3). No commit."""
    order = (
        await session.execute(
            select(Order.status, Order.delivery_type, Order.payment_method_code, Order.user_id)
            .where(Order.id == order_id)
            .with_for_update()
        )
    ).one_or_none()
    if order is None:
        raise AppError(404, "NOT_FOUND", "Ресурс не найден")
    plan = check_transition(
        OrderState(order.status, order.delivery_type, order.payment_method_code),
        new_status,
        actor,
        actor_id=actor_id,
        comment=comment,
        context=await load_context(session, order_id),
    )
    if new_status == S.CANCELLED:
        raise DeferredTransitionError("use cancel_order (§14.3) for cancellations")
    now = await session.scalar(select(func.now()))
    values: dict[str, object] = {"status": new_status}
    if new_status == S.COMPLETED:
        values["completed_at"] = now
    await session.execute(update(Order).where(Order.id == order_id).values(**values))
    await _side_effects(
        session,
        order_id,
        new_status,
        delivery_type=order.delivery_type,
        actor_id=actor_id,
        now=now,
    )
    created_at = await session.scalar(
        insert(OrderStatusHistory)
        .values(
            order_id=order_id,
            old_status=plan.old_status,
            new_status=new_status,
            changed_by=actor_id,
            comment=comment.strip() if comment and comment.strip() else None,
            is_admin_override=plan.is_admin_override,
        )
        .returning(OrderStatusHistory.created_at)
    )
    await publish(
        session,
        OrderStatusChanged(
            order_id=order_id,
            customer_id=order.user_id,
            old_status=plan.old_status,
            new_status=new_status,
            changed_by=actor_id,
            occurred_at=created_at or datetime.now(UTC),
        ),
    )
    return plan
