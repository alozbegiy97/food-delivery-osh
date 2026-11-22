"""Mock payment under concurrency (stage 7; DEC-149; DATABASE_SCHEMA.md §8.2, §14.5).

Real committed transactions on db-test (verified by `async_engine`): two
confirmations of one attempt at the same time, success against failure, and
the timeout job against a confirmation that holds the order lock. The rows
created here (user, order, payments, history; the mock_card method if it
was missing) are deleted afterwards.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.orders.models import Order
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.payments.schemas import MockConfirmIn
from app.modules.payments.service import confirm_mock, mock_reference
from app.modules.payments.timeouts import cancel_expired_orders
from app.modules.users.models import User

pytestmark = pytest.mark.db


@dataclass
class Committed:
    user_id: uuid.UUID
    order_id: uuid.UUID
    attempt_id: uuid.UUID


@pytest.fixture
async def committed_order(async_engine: AsyncEngine) -> AsyncIterator[Committed]:
    created_method = False
    async with async_engine.begin() as conn:
        method_id = await conn.scalar(
            select(PaymentMethod.id).where(PaymentMethod.code == "mock_card")
        )
        if method_id is None:
            created_method = True
            method_id = await conn.scalar(
                insert(PaymentMethod).values(code="mock_card").returning(PaymentMethod.id)
            )
        user_id = await conn.scalar(
            insert(User)
            .values(
                email=f"pay-{uuid.uuid4().hex}@example.com",
                password_hash="not-a-real-hash",
                full_name="Concurrency",
            )
            .returning(User.id)
        )
        order_id = await conn.scalar(
            insert(Order)
            .values(
                user_id=user_id,
                language_code="ru",
                delivery_type="pickup",
                payment_method_code="mock_card",
                subtotal=420,
                delivery_fee=0,
                total_amount=420,
                customer_name="Concurrency",
                customer_phone="+996700123456",
                payment_due_at=func.now() + text("interval '30 minutes'"),
            )
            .returning(Order.id)
        )
        attempt_id = await conn.scalar(
            insert(Payment)
            .values(
                order_id=order_id,
                payment_method_id=method_id,
                amount=420,
                status="pending",
                is_simulated=True,
                transaction_reference=mock_reference(),
            )
            .returning(Payment.id)
        )
    try:
        yield Committed(user_id, order_id, attempt_id)
    finally:
        async with async_engine.begin() as conn:
            await conn.execute(delete(Payment).where(Payment.order_id == order_id))
            await conn.execute(delete(Order).where(Order.id == order_id))  # history: CASCADE
            await conn.execute(delete(User).where(User.id == user_id))
            if created_method:
                await conn.execute(delete(PaymentMethod).where(PaymentMethod.id == method_id))


async def _confirm(engine: AsyncEngine, data: Committed, outcome: str):  # noqa: ANN202
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            return await confirm_mock(
                session,
                data.user_id,
                MockConfirmIn(order_id=data.order_id, attempt_id=data.attempt_id, outcome=outcome),
            )
        except AppError as exc:
            return exc


async def _statuses(engine: AsyncEngine, order_id: uuid.UUID) -> list[str]:
    async with engine.connect() as conn:
        return sorted(
            (await conn.scalars(select(Payment.status).where(Payment.order_id == order_id))).all()
        )


async def test_two_parallel_successes_pay_once(
    async_engine: AsyncEngine, committed_order: Committed
) -> None:
    first, second = await asyncio.gather(
        _confirm(async_engine, committed_order, "success"),
        _confirm(async_engine, committed_order, "success"),
    )
    assert not isinstance(first, AppError) and not isinstance(second, AppError)
    assert first.attempt == second.attempt  # the second one got the stored result
    assert first.payment_status == second.payment_status == "succeeded"
    assert await _statuses(async_engine, committed_order.order_id) == ["succeeded"]


async def test_parallel_success_and_failure_never_both_apply(
    async_engine: AsyncEngine, committed_order: Committed
) -> None:
    results = await asyncio.gather(
        _confirm(async_engine, committed_order, "success"),
        _confirm(async_engine, committed_order, "failure"),
    )
    statuses = await _statuses(async_engine, committed_order.order_id)
    refused = [r for r in results if isinstance(r, AppError)]
    assert len(refused) == 1 and refused[0].code == "PAYMENT_NOT_ALLOWED"
    # Either the success won (one row) or the failure won (failed + new pending).
    assert statuses in (["succeeded"], ["failed", "pending"])


async def test_timeout_skips_an_order_locked_by_a_confirmation(
    async_engine: AsyncEngine, committed_order: Committed
) -> None:
    async with async_engine.begin() as conn:
        await conn.execute(
            Order.__table__.update()
            .where(Order.id == committed_order.order_id)
            .values(payment_due_at=func.now() - text("interval '1 minute'"))
        )

    def factory() -> AsyncSession:
        return AsyncSession(async_engine, expire_on_commit=False)

    async with AsyncSession(async_engine) as holder:
        # A confirmation (or another worker) holds the order row.
        await holder.execute(
            select(Order.id).where(Order.id == committed_order.order_id).with_for_update()
        )
        skipped = await asyncio.wait_for(cancel_expired_orders(factory, batch_size=50), timeout=5)
        assert committed_order.order_id not in skipped.cancelled  # SKIP LOCKED, no waiting
        await holder.rollback()

    done = await cancel_expired_orders(factory, batch_size=50)
    assert committed_order.order_id in done.cancelled
    async with async_engine.connect() as conn:
        status = await conn.scalar(select(Order.status).where(Order.id == committed_order.order_id))
    assert status == "cancelled"
    assert await _statuses(async_engine, committed_order.order_id) == ["cancelled"]
    # A late confirmation of the expired attempt is refused.
    late = await _confirm(async_engine, committed_order, "success")
    assert isinstance(late, AppError) and late.code == "PAYMENT_NOT_ALLOWED"
