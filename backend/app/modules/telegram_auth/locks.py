"""Advisory lock per Telegram ID and lock timeout (DEC-152 п. 3, DEC-154, U1).

`pg_advisory_xact_lock(int4, int4)` — the two-key form lives in a lock
space separate from the one-key bigint locks of seed, create-admin and the
zone editor, so they never collide. The Telegram ID (up to 2^63-1) is folded
into 32 bits; two IDs with the same fold only wait for each other.

Lock order of every operation that creates (or, at stage 10, deletes) a
link: this advisory lock -> `users` (`FOR NO KEY UPDATE`) -> `telegram_links`.
It is never taken while a `users` row lock is held.
"""

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

# "MA" + 0x0002: fixed namespace of the Mini App link locks (int4).
LOCK_NAMESPACE = 0x4D410002
# U1: waiting for any lock inside register/link is bounded.
LOCK_TIMEOUT = "5s"
LOCK_NOT_AVAILABLE = "55P03"  # SQLSTATE lock_not_available (lock_timeout)


def fold_telegram_id(telegram_id: int) -> int:
    """Fold a 64-bit Telegram ID into a signed int4 lock key."""
    folded = (telegram_id ^ (telegram_id >> 32)) & 0xFFFFFFFF
    return folded - 0x1_0000_0000 if folded >= 0x8000_0000 else folded


async def set_lock_timeout(session: AsyncSession) -> None:
    """Bound lock waits for the rest of the current transaction only."""
    await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


async def lock_telegram_id(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), CAST(:key AS integer))"),
        {"namespace": LOCK_NAMESPACE, "key": fold_telegram_id(telegram_id)},
    )


def is_lock_timeout(exc: DBAPIError) -> bool:
    """Only the lock_timeout SQLSTATE; deadlocks and other errors are not."""
    return getattr(exc.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE
