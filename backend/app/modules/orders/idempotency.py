"""Idempotent order creation (DATABASE_SCHEMA.md §14.2; DEC-59, DEC-109, DEC-148).

Runs at the very start of the order transaction (§14.1 step 1), before the
cart is locked, so the lock order is always: idempotency key -> cart.

1. `SET LOCAL lock_timeout` (5 s): waiting for a parallel request with the
   same key ends with `409 IDEMPOTENCY_IN_PROGRESS`.
2. An EXPIRED row of the same user, scope and key is deleted (DEC-148 until
   the worker cleanup of stage 10); valid keys are never deleted.
3. `INSERT … ON CONFLICT DO NOTHING`: if another transaction is inserting
   the same key, PostgreSQL waits for it; after its commit the conflict is
   resolved by reading the stored row, after its rollback the insert goes
   through.
4. Existing row: same hash -> stored response (replay); other hash -> 409.
Errors roll back the whole transaction including the key, so failed
attempts are never stored as results.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.orders.models import IdempotencyKey

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
LOCK_TIMEOUT = "5s"
LOCK_NOT_AVAILABLE = "55P03"


def validate_key(value: str | None) -> str:
    if value is None or not KEY_PATTERN.fullmatch(value):
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Проверьте данные",
            details=[
                {
                    "field": "Idempotency-Key",
                    "message": "обязательный заголовок: 1–128 символов [A-Za-z0-9_-]",
                }
            ],
        )
    return value


def request_hash(canonical: dict[str, Any]) -> str:
    body = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Replay:
    status: int
    body: dict[str, Any]


def _in_progress() -> AppError:
    return AppError(409, "IDEMPOTENCY_IN_PROGRESS", "Запрос с этим ключом ещё выполняется")


async def begin(
    session: AsyncSession, *, user_id: uuid.UUID, scope: str, key: str, digest: str
) -> uuid.UUID | Replay:
    """Register the key; its id, or the stored response to replay."""
    now = datetime.now(UTC)
    try:
        await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        await session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.key == key,
                IdempotencyKey.expires_at <= now,
            )
        )
        key_id = await session.scalar(
            pg_insert(IdempotencyKey)
            .values(
                user_id=user_id,
                scope=scope,
                key=key,
                request_hash=digest,
                expires_at=now + timedelta(hours=get_settings().idempotency_key_ttl_hours),
            )
            .on_conflict_do_nothing(index_elements=["user_id", "scope", "key"])
            .returning(IdempotencyKey.id)
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            await session.rollback()
            raise _in_progress() from None
        raise
    if key_id is not None:
        return key_id

    stored = (
        await session.execute(
            select(
                IdempotencyKey.request_hash,
                IdempotencyKey.response_status,
                IdempotencyKey.response_body,
            ).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.key == key,
            )
        )
    ).one()
    await session.rollback()
    if stored.request_hash != digest:
        raise AppError(
            409,
            "IDEMPOTENCY_KEY_CONFLICT",
            "Этот ключ уже использован для другого запроса",
        )
    if stored.response_status is None or stored.response_body is None:
        # Committed rows always carry a response (errors roll back); kept as a guard.
        raise _in_progress()
    return Replay(status=stored.response_status, body=stored.response_body)


async def finish(
    session: AsyncSession, key_id: uuid.UUID, *, status: int, body: dict[str, Any]
) -> None:
    """Store the successful result in the same transaction (§14.1 step 15)."""
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == key_id)
        .values(response_status=status, response_body=body)
    )
