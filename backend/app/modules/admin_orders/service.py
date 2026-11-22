"""Order management of the administrator (API §9 "Orders"; DATABASE_SCHEMA.md
§7.1, §7.6, §14.3; DEC-45, DEC-82, DEC-97, DEC-100, DEC-101, DEC-150).

All transitions go through the existing state machine (`change_status`) and
the single cancellation operation (`cancel_order`); this module only adds the
work queue, filters, the administrator view and the review of cancellation
requests. Unpaid mock_card orders are outside the work queue and accept no
action (DEC-97): `409 PAYMENT_REQUIRED`.
"""

import math
import uuid
from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.periods import make_period
from app.modules.addresses.schemas import Pagination
from app.modules.admin_orders.schemas import (
    AdminHistoryOut,
    AdminOrderDetail,
    AdminOrderList,
    AdminOrderSummary,
    AdminRequestList,
    AdminRequestOut,
    RequestRejection,
    StatusChange,
)
from app.modules.courier import assignments as courier_assignments
from app.modules.delivery.enums import AssignmentStatus
from app.modules.delivery.models import CourierAssignment, Delivery, DeliveryZone
from app.modules.orders.cancel import cancel_order
from app.modules.orders.enums import (
    CancellationReasonCode,
    CancellationRequestStatus,
    OrderStatus,
)
from app.modules.orders.models import (
    CancellationRequest,
    Order,
    OrderItem,
    OrderStatusHistory,
)
from app.modules.orders.queries import load_order_detail
from app.modules.orders.status import (
    TRANSITIONS,
    Actor,
    DeferredTransitionError,
    OrderState,
    change_status,
    check_transition,
    load_context,
)
from app.modules.payments.enums import PaymentMethodCode
from app.modules.payments.models import Payment
from app.modules.payments.service import summary_status
from app.modules.users.models import User


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def _awaiting_payment():  # noqa: ANN202 - SQL expression
    """Unpaid mock_card order still within its deadline (DEC-84, DEC-97)."""
    return and_(
        Order.status == OrderStatus.PENDING,
        Order.payment_method_code == PaymentMethodCode.MOCK_CARD,
        Order.payment_due_at.is_not(None),
    )


def _payment_required() -> AppError:
    return AppError(409, "PAYMENT_REQUIRED", "Заказ ещё не оплачен")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_orders(
    session: AsyncSession,
    *,
    status: str | None,
    delivery_type: str | None,
    date_from: date | None,
    date_to: date | None,
    number: str | None,
    awaiting_payment: bool,
    page: int,
    page_size: int,
) -> AdminOrderList:
    conditions = [_awaiting_payment() if awaiting_payment else ~_awaiting_payment()]
    if status:
        conditions.append(Order.status == status)
    if delivery_type:
        conditions.append(Order.delivery_type == delivery_type)
    if date_from or date_to:
        period = make_period(date_from, date_to)
        conditions += [Order.created_at >= period.start, Order.created_at < period.end]
    if number and number.strip():
        conditions.append(
            Order.order_number.ilike(f"%{_escape_like(number.strip())}%", escape="\\")
        )

    total = int(
        await session.scalar(select(func.count()).select_from(Order).where(*conditions)) or 0
    )
    counts = (
        select(OrderItem.order_id, func.sum(OrderItem.quantity).label("items_count"))
        .group_by(OrderItem.order_id)
        .subquery()
    )
    pending_request = exists().where(
        CancellationRequest.order_id == Order.id,
        CancellationRequest.status == CancellationRequestStatus.PENDING,
    )
    active_courier = (
        select(User.full_name)
        .join(CourierAssignment, CourierAssignment.courier_id == User.id)
        .where(
            CourierAssignment.order_id == Order.id,
            CourierAssignment.status == AssignmentStatus.ACTIVE,
        )
        .correlate(Order)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(
            Order,
            func.coalesce(counts.c.items_count, 0).label("items_count"),
            pending_request.label("has_request"),
            _awaiting_payment().label("awaiting"),
            courier_assignments.needs_courier().label("needs_courier"),
            active_courier.label("courier_name"),
        )
        .outerjoin(counts, counts.c.order_id == Order.id)
        .where(*conditions)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    page_rows = rows.all()
    statuses: dict[uuid.UUID, list[str]] = {row[0].id: [] for row in page_rows}
    if statuses:
        for order_id, payment_status in await session.execute(
            select(Payment.order_id, Payment.status)
            .where(Payment.order_id.in_(list(statuses)))
            .order_by(Payment.created_at, Payment.id)
        ):
            statuses[order_id].append(payment_status)
    items = []
    for order, items_count, has_request, awaiting, needs_courier, courier_name in page_rows:
        items.append(
            AdminOrderSummary(
                id=order.id,
                order_number=order.order_number,
                status=order.status,
                delivery_type=order.delivery_type,
                payment_method_code=order.payment_method_code,
                payment_status=summary_status(statuses[order.id]),
                awaiting_payment=bool(awaiting),
                total_amount=order.total_amount,
                currency=order.currency,
                customer_name=order.customer_name,
                customer_phone=order.customer_phone,
                items_count=int(items_count),
                has_pending_cancellation=bool(has_request),
                needs_courier=bool(needs_courier),
                courier_name=courier_name,
                created_at=order.created_at,
            )
        )
    return AdminOrderList(
        items=items,
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def _allowed_statuses(session: AsyncSession, order: Order) -> list[str]:
    context = await load_context(session, order.id)
    state = OrderState(order.status, order.delivery_type, order.payment_method_code)
    allowed = []
    for (old, new), _rules in TRANSITIONS.items():
        if old != order.status:
            continue
        try:
            check_transition(state, new, Actor.ADMIN, comment="x", context=context)
        except AppError:
            continue
        allowed.append(new.value if hasattr(new, "value") else str(new))
    return allowed


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> AdminOrderDetail:
    detail = await load_order_detail(session, order_id, owner_id=None)
    order = await session.scalar(select(Order).where(Order.id == order_id))
    assert order is not None  # noqa: S101 - loaded above
    awaiting = bool(
        await session.scalar(select(exists().where(Order.id == order_id, _awaiting_payment())))
    )
    email = await session.scalar(select(User.email).where(User.id == order.user_id))
    zone_name = await session.scalar(
        select(DeliveryZone.name)
        .join(Delivery, Delivery.delivery_zone_id == DeliveryZone.id)
        .where(Delivery.order_id == order_id)
    )
    history = [
        AdminHistoryOut(
            old_status=row.old_status,
            new_status=row.new_status,
            comment=row.comment,
            is_admin_override=row.is_admin_override,
            changed_by_name=row.full_name,
            created_at=row.created_at,
        )
        for row in await session.execute(
            select(
                OrderStatusHistory.old_status,
                OrderStatusHistory.new_status,
                OrderStatusHistory.comment,
                OrderStatusHistory.is_admin_override,
                OrderStatusHistory.created_at,
                User.full_name,
            )
            .outerjoin(User, User.id == OrderStatusHistory.changed_by)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
        )
    ]
    return AdminOrderDetail(
        **detail.model_dump(),
        customer_email=email,
        awaiting_payment=awaiting,
        delivery_zone_name=zone_name,
        admin_history=history,
        allowed_statuses=[] if awaiting else await _allowed_statuses(session, order),
        assignments=await courier_assignments.order_assignments(session, order_id),
        needs_courier=bool(
            await session.scalar(
                select(exists().where(Order.id == order_id, courier_assignments.needs_courier()))
            )
        ),
        can_assign_courier=order.delivery_type == "delivery"
        and order.status in courier_assignments.ASSIGNABLE_STATUSES,
        delivered_at=await session.scalar(
            select(Delivery.delivered_at).where(Delivery.order_id == order_id)
        ),
    )


async def _lock_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise not_found()
    if order.status == OrderStatus.PENDING and (
        order.payment_method_code == PaymentMethodCode.MOCK_CARD
        and order.payment_due_at is not None
    ):
        raise _payment_required()  # DEC-97: no actions on unpaid orders
    return order


def _cancellation_not_allowed() -> AppError:
    return AppError(409, "CANCELLATION_NOT_ALLOWED", "В этом статусе заказ отменить нельзя")


async def change_order_status(
    session: AsyncSession, order_id: uuid.UUID, payload: StatusChange, *, admin_id: uuid.UUID
) -> AdminOrderDetail:
    await _lock_order(session, order_id)
    try:
        if payload.status == OrderStatus.CANCELLED:
            # Single idempotent cancellation (DEC-82, DEC-101).
            try:
                await cancel_order(
                    session,
                    order_id,
                    reason_code=CancellationReasonCode.ADMIN_DECISION.value,
                    comment=payload.comment or "",
                    actor=Actor.ADMIN,
                    actor_id=admin_id,
                )
            except AppError as exc:
                # DEC-33: no cancellation from out_for_delivery or a final
                # status; same code as approving a request (API §1.1).
                if exc.code == "INVALID_STATUS_TRANSITION":
                    raise _cancellation_not_allowed() from None
                raise
        else:
            await change_status(
                session,
                order_id,
                payload.status,
                Actor.ADMIN,
                actor_id=admin_id,
                comment=payload.comment,
            )
    except DeferredTransitionError:
        raise AppError(409, "INVALID_STATUS_TRANSITION", "Переход статуса не разрешён") from None
    await session.commit()
    return await get_order(session, order_id)


# --------------------------------------------------------------------------
# Courier assignment (DEC-48…DEC-51, DEC-67, DEC-151)
# --------------------------------------------------------------------------


async def assign_courier(
    session: AsyncSession, order_id: uuid.UUID, courier_id: uuid.UUID, *, admin_id: uuid.UUID
) -> AdminOrderDetail:
    await _lock_order(session, order_id)  # orders first (DEC-151 п. 6)
    await courier_assignments.assign(session, order_id, courier_id, admin_id=admin_id)
    return await get_order(session, order_id)


async def auto_assign_courier(session: AsyncSession, order_id: uuid.UUID) -> AdminOrderDetail:
    await _lock_order(session, order_id)
    await courier_assignments.auto_assign(session, order_id)
    return await get_order(session, order_id)


# --------------------------------------------------------------------------
# Cancellation requests
# --------------------------------------------------------------------------


async def _request_out(session: AsyncSession, request_id: uuid.UUID) -> AdminRequestOut:
    reviewer = User.__table__.alias("reviewer")
    row = (
        await session.execute(
            select(
                CancellationRequest,
                Order.order_number,
                Order.status.label("order_status"),
                Order.customer_name,
                reviewer.c.full_name.label("reviewer_name"),
            )
            .join(Order, Order.id == CancellationRequest.order_id)
            .outerjoin(reviewer, reviewer.c.id == CancellationRequest.reviewed_by)
            .where(CancellationRequest.id == request_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found()
    request = row[0]
    return AdminRequestOut(
        id=request.id,
        order_id=request.order_id,
        order_number=row.order_number,
        order_status=row.order_status,
        customer_name=row.customer_name,
        reason=request.reason,
        status=request.status,
        admin_comment=request.admin_comment,
        created_at=request.created_at,
        reviewed_at=request.reviewed_at,
        reviewed_by_name=row.reviewer_name,
    )


async def list_requests(
    session: AsyncSession, *, status: str, page: int, page_size: int
) -> AdminRequestList:
    conditions = [] if status == "all" else [CancellationRequest.status == status]
    total = int(
        await session.scalar(
            select(func.count()).select_from(CancellationRequest).where(*conditions)
        )
        or 0
    )
    ids = list(
        await session.scalars(
            select(CancellationRequest.id)
            .where(*conditions)
            .order_by(CancellationRequest.created_at.desc(), CancellationRequest.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return AdminRequestList(
        items=[await _request_out(session, request_id) for request_id in ids],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


def _already_reviewed() -> AppError:
    return AppError(409, "CANCELLATION_NOT_ALLOWED", "Запрос уже рассмотрен с другим решением")


async def _locked_request(session: AsyncSession, request_id: uuid.UUID) -> CancellationRequest:
    order_id = await session.scalar(
        select(CancellationRequest.order_id).where(CancellationRequest.id == request_id)
    )
    if order_id is None:
        raise not_found()
    # Lock order: orders -> cancellation_requests (as in cancel_order).
    await session.execute(select(Order.id).where(Order.id == order_id).with_for_update())
    request = await session.scalar(
        select(CancellationRequest).where(CancellationRequest.id == request_id).with_for_update()
    )
    assert request is not None  # noqa: S101
    return request


async def approve_request(
    session: AsyncSession, request_id: uuid.UUID, *, admin_id: uuid.UUID
) -> AdminRequestOut:
    request = await _locked_request(session, request_id)
    if request.status == CancellationRequestStatus.APPROVED:
        await session.rollback()
        return await _request_out(session, request_id)  # idempotent
    if request.status == CancellationRequestStatus.REJECTED:
        raise _already_reviewed()
    await _lock_order(session, request.order_id)
    try:
        await cancel_order(
            session,
            request.order_id,
            reason_code=CancellationReasonCode.CUSTOMER_REQUEST.value,
            comment=request.reason,
            actor=Actor.ADMIN,
            actor_id=admin_id,
        )
    except AppError as exc:
        if exc.code == "INVALID_STATUS_TRANSITION":
            raise _cancellation_not_allowed() from None
        raise
    await session.commit()
    return await _request_out(session, request_id)


async def reject_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    payload: RequestRejection,
    *,
    admin_id: uuid.UUID,
) -> AdminRequestOut:
    request = await _locked_request(session, request_id)
    if request.status == CancellationRequestStatus.REJECTED:
        await session.rollback()
        return await _request_out(session, request_id)  # idempotent
    if request.status == CancellationRequestStatus.APPROVED:
        raise _already_reviewed()
    request.status = CancellationRequestStatus.REJECTED.value
    request.admin_comment = payload.admin_comment
    request.reviewed_by = admin_id
    request.reviewed_at = await session.scalar(select(func.now()))
    await session.commit()
    return await _request_out(session, request_id)
