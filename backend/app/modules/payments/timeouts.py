"""Payment timeout of unpaid mock_card orders (DEC-84, DEC-97, DEC-104, DEC-149;
DATABASE_SCHEMA.md §14.5).

One run handles up to `batch_size` expired orders. Every order is taken with
`FOR UPDATE SKIP LOCKED` (a parallel confirmation or another worker keeps its
row) and cancelled by the single cancellation operation in its OWN
transaction, so one broken order never blocks the others. A paid order has
`payment_due_at = NULL` and a succeeded attempt, so it is never selected; the
condition is re-evaluated under the row lock. A repeated run changes nothing.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.cancel import cancel_order
from app.modules.orders.enums import CancellationReasonCode, OrderStatus
from app.modules.orders.models import Order
from app.modules.orders.status import Actor
from app.modules.payments.enums import PaymentMethodCode, PaymentStatus
from app.modules.payments.models import Payment

logger = logging.getLogger(__name__)

# History comment of a system cancellation (DEC-98, DEC-132).
TIMEOUT_COMMENT = CancellationReasonCode.PAYMENT_TIMEOUT.value

SessionFactory = Callable[[], AsyncSession]


@dataclass
class TimeoutRun:
    cancelled: list[uuid.UUID] = field(default_factory=list)
    failed: list[uuid.UUID] = field(default_factory=list)


def _expired():  # noqa: ANN202 - SQLAlchemy select
    return select(Order.id).where(
        Order.status == OrderStatus.PENDING,
        Order.payment_method_code == PaymentMethodCode.MOCK_CARD,
        Order.payment_due_at.is_not(None),
        Order.payment_due_at < func.now(),
        # Defence in depth: a paid order is never cancelled as unpaid.
        ~exists().where(Payment.order_id == Order.id, Payment.status == PaymentStatus.SUCCEEDED),
    )


async def cancel_expired_orders(session_factory: SessionFactory, *, batch_size: int) -> TimeoutRun:
    run = TimeoutRun()
    while len(run.cancelled) + len(run.failed) < batch_size:
        async with session_factory() as session:
            query = _expired().order_by(Order.payment_due_at, Order.id).limit(1)
            if run.failed:
                query = query.where(Order.id.not_in(run.failed))
            order_id = await session.scalar(query.with_for_update(skip_locked=True))
            if order_id is None:
                break
            try:
                await cancel_order(
                    session,
                    order_id,
                    reason_code=CancellationReasonCode.PAYMENT_TIMEOUT.value,
                    comment=TIMEOUT_COMMENT,
                    actor=Actor.SYSTEM,
                    actor_id=None,
                )
                await session.commit()
                run.cancelled.append(order_id)
            except Exception:  # one broken order must not stop the job (DEC-104)
                await session.rollback()
                run.failed.append(order_id)
                logger.exception("payment timeout: order %s was not cancelled", order_id)
    if run.cancelled:
        logger.info("payment timeout: %d unpaid order(s) cancelled", len(run.cancelled))
    return run
