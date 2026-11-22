"""Customer cancellation requests (API §6.3; DATABASE_SCHEMA.md §7.6; DEC-38,
DEC-42, DEC-148).

The customer never cancels an order directly: he creates a request that an
administrator reviews (stage 8). Allowed in `pending`, `confirmed`,
`preparing`; at most one pending request per order (partial UNIQUE index);
after a rejection a new request may be sent. The order row is locked so a
parallel request or status change is applied one after another.
"""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.orders.models import CancellationRequest, Order
from app.modules.orders.queries import CANCELLATION_REQUEST_STATUSES, has_pending_request
from app.modules.orders.schemas import CancellationRequestCreate, CancellationRequestOut


def _pending_exists() -> AppError:
    return AppError(409, "CANCELLATION_REQUEST_PENDING", "Запрос отмены уже ожидает рассмотрения")


async def create_request(
    session: AsyncSession,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
    payload: CancellationRequestCreate,
) -> CancellationRequestOut:
    status = await session.scalar(
        select(Order.status).where(Order.id == order_id, Order.user_id == user_id).with_for_update()
    )
    if status is None:
        raise AppError(404, "NOT_FOUND", "Ресурс не найден")
    if status not in CANCELLATION_REQUEST_STATUSES:
        await session.rollback()
        raise AppError(409, "CANCELLATION_NOT_ALLOWED", "В этом статусе отмену запросить нельзя")
    if await has_pending_request(session, order_id):
        await session.rollback()
        raise _pending_exists()
    try:
        row = (
            await session.execute(
                insert(CancellationRequest)
                .values(order_id=order_id, user_id=user_id, reason=payload.reason)
                .returning(
                    CancellationRequest.id,
                    CancellationRequest.reason,
                    CancellationRequest.status,
                    CancellationRequest.admin_comment,
                    CancellationRequest.created_at,
                    CancellationRequest.reviewed_at,
                )
            )
        ).one()
    except IntegrityError:
        # The partial UNIQUE index is the last line of defence.
        await session.rollback()
        raise _pending_exists() from None
    await session.commit()
    return CancellationRequestOut.model_validate(row, from_attributes=True)
