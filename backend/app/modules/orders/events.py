"""In-process domain events of orders (DEC-79, DATABASE_SCHEMA.md §14.3).

Every status change publishes `OrderStatusChanged` inside the same
transaction. Handlers receive the session of that transaction, so anything
they write (notifications, Telegram outbox — stage 10) commits or rolls back
together with the status change. Stage 6 registers no handlers.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OrderStatusChanged:
    order_id: uuid.UUID
    customer_id: uuid.UUID
    old_status: str | None  # None for the first status of a new order
    new_status: str
    changed_by: uuid.UUID | None  # None for system transitions
    occurred_at: datetime


Handler = Callable[[AsyncSession, OrderStatusChanged], Awaitable[None]]

_handlers: list[Handler] = []


def subscribe(handler: Handler) -> None:
    if handler not in _handlers:
        _handlers.append(handler)


def unsubscribe(handler: Handler) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


async def publish(session: AsyncSession, event: OrderStatusChanged) -> None:
    """Run every handler in the caller's transaction; an exception rolls the
    whole transaction back (the change and its consequences are atomic)."""
    for handler in list(_handlers):
        await handler(session, event)
