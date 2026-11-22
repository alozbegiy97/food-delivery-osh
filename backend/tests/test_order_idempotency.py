"""Idempotency key under concurrency (stage 6; DATABASE_SCHEMA.md §14.2; DEC-59,
DEC-109, DEC-148).

Real transactions on db-test (verified by the `async_engine` fixture): a
second request with the same key waits on the unique index while the first
one is open, ends with `409 IDEMPOTENCY_IN_PROGRESS` after `lock_timeout`,
replays the stored response after a commit and goes through after a
rollback. The committed user and his keys are removed afterwards.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.orders import idempotency
from app.modules.orders.models import IdempotencyKey
from app.modules.users.models import User

pytestmark = pytest.mark.db

SCOPE = "create_order"


@pytest.fixture
async def committed_user(async_engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    async with async_engine.begin() as conn:
        user_id = await conn.scalar(
            insert(User)
            .values(
                email=f"idem-{uuid.uuid4().hex}@example.com",
                password_hash="not-a-real-hash",
                full_name="Idempotency",
            )
            .returning(User.id)
        )
    try:
        yield user_id
    finally:
        async with async_engine.begin() as conn:
            await conn.execute(delete(User).where(User.id == user_id))  # keys: ON DELETE CASCADE


async def _begin(session: AsyncSession, user_id: uuid.UUID, key: str, digest: str):  # noqa: ANN202
    return await idempotency.begin(session, user_id=user_id, scope=SCOPE, key=key, digest=digest)


async def test_parallel_requests_with_one_key(
    async_engine: AsyncEngine, committed_user: uuid.UUID
) -> None:
    key = uuid.uuid4().hex
    async with AsyncSession(async_engine) as first, AsyncSession(async_engine) as second:
        key_id = await _begin(first, committed_user, key, "a" * 64)
        assert isinstance(key_id, uuid.UUID)

        # While the first transaction is open the second one waits, then gives up.
        started = asyncio.get_running_loop().time()
        with pytest.raises(AppError) as info:
            await _begin(second, committed_user, key, "a" * 64)
        assert info.value.code == "IDEMPOTENCY_IN_PROGRESS"
        assert asyncio.get_running_loop().time() - started >= 4.5  # lock_timeout 5 s

        await idempotency.finish(first, key_id, status=201, body={"id": "order-1"})
        await first.commit()

    async with AsyncSession(async_engine) as third:
        replay = await _begin(third, committed_user, key, "a" * 64)
        assert replay == idempotency.Replay(status=201, body={"id": "order-1"})
    async with AsyncSession(async_engine) as fourth:
        with pytest.raises(AppError) as info:
            await _begin(fourth, committed_user, key, "b" * 64)
        assert info.value.code == "IDEMPOTENCY_KEY_CONFLICT"


async def test_waiting_request_proceeds_after_a_rollback(
    async_engine: AsyncEngine, committed_user: uuid.UUID
) -> None:
    key = uuid.uuid4().hex
    async with AsyncSession(async_engine) as first, AsyncSession(async_engine) as second:
        assert isinstance(await _begin(first, committed_user, key, "a" * 64), uuid.UUID)
        waiting = asyncio.create_task(_begin(second, committed_user, key, "a" * 64))
        await asyncio.sleep(0.5)
        assert not waiting.done()
        await first.rollback()  # e.g. PRICE_CHANGED: the key is not kept
        second_key = await asyncio.wait_for(waiting, timeout=5)
        assert isinstance(second_key, uuid.UUID)
        await second.commit()

    async with async_engine.connect() as conn:
        count = await conn.scalar(
            select(func.count())
            .select_from(IdempotencyKey)
            .where(IdempotencyKey.user_id == committed_user)
        )
    assert count == 1
