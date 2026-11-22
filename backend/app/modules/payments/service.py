"""Payment methods and the simulated card payment (API §7; DATABASE_SCHEMA.md
§8.2; DEC-44…DEC-47, DEC-97, DEC-99, DEC-149).

A mock payment attempt is one `payments` row; its id is the `attempt_id`.
Every confirmation locks the order row first (lock order: orders ->
payments, the same as order creation, cancellation and the timeout job), so
parallel requests for one order run one after another and can never produce
two successful payments (also guarded by the partial UNIQUE index).
Nothing here touches real money or card data.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.orders.enums import CURRENCY_KGS, OrderStatus
from app.modules.orders.models import Order
from app.modules.payments.enums import PaymentMethodCode, PaymentStatus
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.payments.schemas import (
    AttemptOut,
    MockConfirmIn,
    MockConfirmOut,
    PaymentMethodList,
    PaymentMethodOut,
)

SUCCESS = "success"
FAILURE = "failure"


def mock_reference() -> str:
    """Unique simulated reference of one attempt; not a bank identifier."""
    return f"MOCK-{uuid.uuid4().hex.upper()}"


def summary_status(statuses: list[str]) -> str | None:
    """Payment status of an order from its attempts in creation order: a
    successful attempt wins, then an unfinished one, otherwise the latest."""
    if PaymentStatus.SUCCEEDED in statuses:
        return PaymentStatus.SUCCEEDED.value
    if PaymentStatus.PENDING in statuses:
        return PaymentStatus.PENDING.value
    return statuses[-1] if statuses else None


def not_allowed() -> AppError:
    return AppError(409, "PAYMENT_NOT_ALLOWED", "Оплата сейчас невозможна")


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


async def list_methods(session: AsyncSession) -> PaymentMethodList:
    rows = await session.execute(
        select(PaymentMethod.code, PaymentMethod.sort_order)
        .where(PaymentMethod.is_active)
        .order_by(PaymentMethod.sort_order, PaymentMethod.code)
    )
    return PaymentMethodList(
        items=[PaymentMethodOut(code=row.code, sort_order=row.sort_order) for row in rows]
    )


async def active_method_id(session: AsyncSession, code: str) -> uuid.UUID | None:
    return await session.scalar(
        select(PaymentMethod.id).where(PaymentMethod.code == code, PaymentMethod.is_active)
    )


async def add_attempt(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    method_id: uuid.UUID,
    method_code: str,
    amount: Decimal,
) -> uuid.UUID:
    """A new `pending` payment row (cash at checkout, or a mock attempt)."""
    simulated = method_code == PaymentMethodCode.MOCK_CARD
    return await session.scalar(
        insert(Payment)
        .values(
            order_id=order_id,
            payment_method_id=method_id,
            amount=amount,
            currency=CURRENCY_KGS,
            status=PaymentStatus.PENDING.value,
            is_simulated=simulated,
            transaction_reference=mock_reference() if simulated else None,
        )
        .returning(Payment.id)
    )


async def _state(
    session: AsyncSession, order_id: uuid.UUID, attempt_id: uuid.UUID
) -> MockConfirmOut:
    order = (
        await session.execute(
            select(Order.status, Order.payment_due_at).where(Order.id == order_id)
        )
    ).one()
    statuses = list(
        await session.scalars(
            select(Payment.status)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at, Payment.id)
        )
    )
    attempt = (await session.execute(select(Payment).where(Payment.id == attempt_id))).scalar_one()
    return MockConfirmOut(
        order_id=order_id,
        order_status=order.status,
        payment_status=summary_status(statuses) or attempt.status,
        payment_due_at=order.payment_due_at,
        attempt=AttemptOut(
            id=attempt.id,
            status=attempt.status,
            transaction_reference=attempt.transaction_reference,
            amount=attempt.amount,
            currency=attempt.currency,
            created_at=attempt.created_at,
            paid_at=attempt.paid_at,
        ),
    )


async def confirm_mock(
    session: AsyncSession, user_id: uuid.UUID, payload: MockConfirmIn
) -> MockConfirmOut:
    order = (
        await session.execute(
            select(
                Order.id,
                Order.status,
                Order.payment_method_code,
                Order.payment_due_at,
                Order.total_amount,
                func.now().label("now"),
            )
            .where(Order.id == payload.order_id, Order.user_id == user_id)
            .with_for_update()
        )
    ).one_or_none()
    if order is None:
        raise not_found()
    attempt = (
        await session.execute(
            select(Payment.id, Payment.status, Payment.payment_method_id).where(
                Payment.id == payload.attempt_id, Payment.order_id == order.id
            )
        )
    ).one_or_none()
    if attempt is None:
        raise not_found()
    if order.payment_method_code != PaymentMethodCode.MOCK_CARD:
        raise not_allowed()

    if attempt.status == PaymentStatus.PENDING:
        due: datetime | None = order.payment_due_at
        if order.status != OrderStatus.PENDING or due is None or due <= order.now:
            raise not_allowed()
        if payload.outcome == SUCCESS:
            await session.execute(
                update(Payment)
                .where(Payment.id == attempt.id)
                .values(status=PaymentStatus.SUCCEEDED.value, paid_at=order.now)
            )
            # Paid: no deadline any more; the order waits for the staff (DEC-97).
            await session.execute(
                update(Order).where(Order.id == order.id).values(payment_due_at=None)
            )
        else:
            await session.execute(
                update(Payment)
                .where(Payment.id == attempt.id)
                .values(status=PaymentStatus.FAILED.value)
            )
            # The next attempt in the same transaction (DEC-46, DEC-99).
            await add_attempt(
                session,
                order_id=order.id,
                method_id=attempt.payment_method_id,
                method_code=PaymentMethodCode.MOCK_CARD.value,
                amount=order.total_amount,
            )
        await session.commit()
        return await _state(session, order.id, attempt.id)

    # The attempt is already finished: repeat of the same request -> stored result.
    paid = await session.scalar(
        select(
            exists().where(Payment.order_id == order.id, Payment.status == PaymentStatus.SUCCEEDED)
        )
    )
    if payload.outcome == FAILURE and paid:
        raise not_allowed()  # DEC-149: no failure after a successful payment
    same_result = (payload.outcome == SUCCESS and attempt.status == PaymentStatus.SUCCEEDED) or (
        payload.outcome == FAILURE and attempt.status == PaymentStatus.FAILED
    )
    if same_result or (payload.outcome == SUCCESS and paid):
        state = await _state(session, order.id, attempt.id)
        await session.rollback()  # nothing changed; release the order lock
        return state
    raise not_allowed()
