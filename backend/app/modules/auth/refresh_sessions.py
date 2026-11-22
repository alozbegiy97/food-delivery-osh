"""Refresh sessions: rotation, reuse detection and revocation (DEC-140).

Rules (DEC-65, DEC-110, DEC-140):

- A refresh token is 32 random bytes in Base64URL; only its SHA-256 (hex)
  is stored in `refresh_tokens.token_hash`.
- Every operation that changes a user's activity or refresh sessions locks
  the `users` row first (`FOR NO KEY UPDATE`) and only then touches
  `refresh_tokens` rows. Callers of `revoke_family` / `revoke_all_for_user`
  must hold the user lock (`lock_user`) before calling them.
- Nothing here commits. The caller owns the transaction and must run it on
  an engine created by `app.db.session.create_db_engine` (READ COMMITTED).
- Expected refusals are returned as `RefreshOutcome`, never raised, so the
  caller COMMITs the revocation before answering 401. Only an impossible
  rotation (`RefreshRotationConflict`) is raised: the caller rolls back.
- All checks use only column values read by SQL statements in this
  transaction (Core selects), never ORM objects loaded earlier.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.modules.users.models import RefreshToken, User

REFRESH_TOKEN_BYTES = 32
# Base64URL of 32 bytes is 43 characters; anything much longer is not ours
# and is answered as "unknown" without touching the database.
MAX_REFRESH_TOKEN_LENGTH = 128

Executor = AsyncConnection | AsyncSession

_tokens = RefreshToken.__table__
_users = User.__table__


class RefreshStatus(StrEnum):
    OK = "ok"
    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    REUSED = "reused"
    EXPIRED = "expired"


@dataclass(frozen=True)
class RefreshOutcome:
    status: RefreshStatus
    user_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None
    # Raw token for the new cookie; only set for OK. Never shown in repr.
    new_token: str | None = field(default=None, repr=False)


class RefreshRotationConflict(Exception):
    """The old token was not marked rotated in exactly one row.

    The caller must roll back the transaction and answer 401 (DEC-140).
    """


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def decide_refresh(
    *, token_found: bool, owner_active: bool, revoked: bool, expired: bool
) -> RefreshStatus:
    """Order of checks is fixed by DEC-140: unknown, inactive owner,
    rotated/revoked, expired."""
    if not token_found:
        return RefreshStatus.UNKNOWN
    if not owner_active:
        return RefreshStatus.INACTIVE
    if revoked:
        return RefreshStatus.REUSED
    if expired:
        return RefreshStatus.EXPIRED
    return RefreshStatus.OK


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


async def find_token_owner(db: Executor, token_hash: str) -> uuid.UUID | None:
    """Preliminary read without a lock; used only to know which user to lock."""
    result = await db.execute(select(_tokens.c.user_id).where(_tokens.c.token_hash == token_hash))
    return result.scalar_one_or_none()


async def lock_user(db: Executor, user_id: uuid.UUID) -> bool | None:
    """Lock the user row and return `is_active` from this locking read.

    Returns None if the user does not exist.
    """
    result = await db.execute(
        select(_users.c.is_active).where(_users.c.id == user_id).with_for_update(key_share=True)
    )
    return result.scalar_one_or_none()


async def lock_token(db: Executor, token_hash: str):  # noqa: ANN201 - Row
    """Lock and re-read the token row (after the user lock)."""
    result = await db.execute(
        select(
            _tokens.c.id,
            _tokens.c.user_id,
            _tokens.c.family_id,
            _tokens.c.expires_at,
            _tokens.c.revoked_at,
        )
        .where(_tokens.c.token_hash == token_hash)
        .with_for_update()
    )
    return result.one_or_none()


async def _insert_token(
    db: Executor,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    now: datetime,
    ttl: timedelta,
) -> tuple[uuid.UUID, str]:
    raw_token = new_refresh_token()
    token_id = uuid.uuid4()
    await db.execute(
        insert(_tokens).values(
            id=token_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=now + ttl,
        )
    )
    return token_id, raw_token


async def create_family(
    db: Executor, user_id: uuid.UUID, *, now: datetime, ttl: timedelta
) -> tuple[uuid.UUID, str]:
    """Start a new session (login / register). Returns (family_id, raw token)."""
    _require_aware(now)
    family_id = uuid.uuid4()
    _, raw_token = await _insert_token(db, user_id=user_id, family_id=family_id, now=now, ttl=ttl)
    return family_id, raw_token


async def mark_rotated(
    db: Executor, token_id: uuid.UUID, replaced_by_id: uuid.UUID, *, now: datetime
) -> None:
    result = await db.execute(
        update(_tokens)
        .where(_tokens.c.id == token_id, _tokens.c.revoked_at.is_(None))
        .values(revoked_at=now, replaced_by_id=replaced_by_id)
    )
    if result.rowcount != 1:
        raise RefreshRotationConflict


async def revoke_family(db: Executor, family_id: uuid.UUID, *, now: datetime) -> int:
    """Revoke every still-active token of one family. Caller holds the user lock."""
    _require_aware(now)
    result = await db.execute(
        update(_tokens)
        .where(_tokens.c.family_id == family_id, _tokens.c.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount


async def revoke_all_for_user(db: Executor, user_id: uuid.UUID, *, now: datetime) -> int:
    """Revoke every still-active token of the user. Caller holds the user lock."""
    _require_aware(now)
    result = await db.execute(
        update(_tokens)
        .where(_tokens.c.user_id == user_id, _tokens.c.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount


async def refresh_in_transaction(
    db: Executor, raw_token: str | None, *, now: datetime, ttl: timedelta
) -> RefreshOutcome:
    """Run one `/auth/refresh` inside the caller's transaction (DEC-140).

    Raises `RefreshRotationConflict` only for the impossible rotation case;
    every other refusal is returned so the caller can COMMIT it.
    """
    _require_aware(now)
    if not raw_token or len(raw_token) > MAX_REFRESH_TOKEN_LENGTH:
        return RefreshOutcome(RefreshStatus.UNKNOWN)
    token_hash = hash_refresh_token(raw_token)

    owner_id = await find_token_owner(db, token_hash)
    if owner_id is None:
        return RefreshOutcome(RefreshStatus.UNKNOWN)

    is_active = await lock_user(db, owner_id)
    token = await lock_token(db, token_hash)
    if is_active is None or token is None:
        # Deleted between the preliminary read and the locks (cleanup job).
        return RefreshOutcome(RefreshStatus.UNKNOWN)

    status = decide_refresh(
        token_found=True,
        owner_active=bool(is_active),
        revoked=token.revoked_at is not None,
        expired=token.expires_at <= now,
    )
    if status is RefreshStatus.INACTIVE:
        await revoke_all_for_user(db, owner_id, now=now)
    elif status is RefreshStatus.REUSED:
        await revoke_family(db, token.family_id, now=now)
    if status is not RefreshStatus.OK:
        return RefreshOutcome(status, user_id=owner_id, family_id=token.family_id)

    new_id, new_raw = await _insert_token(
        db, user_id=owner_id, family_id=token.family_id, now=now, ttl=ttl
    )
    await mark_rotated(db, token.id, new_id, now=now)
    return RefreshOutcome(
        RefreshStatus.OK, user_id=owner_id, family_id=token.family_id, new_token=new_raw
    )
