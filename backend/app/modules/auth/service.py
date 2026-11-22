"""Auth use cases: register, login, refresh, logout, password change (DEC-140),
adding email and password to a Telegram-only account (DEC-142).

Transaction rules:

- Every function owns the transaction of the request session and ends it
  with an explicit `commit()`; the router answers only after that commit
  returned. If commit raises, the exception propagates and the request
  ends with 500 INTERNAL_ERROR, without a new or cleared cookie.
- Expected refusals that revoke tokens are committed first and raised
  afterwards (DEC-140, "Фиксация результата до ответа").
- Locks are always taken users -> refresh_tokens (`refresh_sessions`).
- Argon2 runs in a worker thread: it is CPU-bound.
- Nothing here logs passwords, hashes or tokens.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import (
    AccessToken,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)
from app.modules.auth import errors
from app.modules.auth.refresh_sessions import (
    MAX_REFRESH_TOKEN_LENGTH,
    RefreshRotationConflict,
    RefreshStatus,
    create_family,
    find_token_owner,
    hash_refresh_token,
    lock_token,
    lock_user,
    refresh_in_transaction,
    revoke_all_for_user,
    revoke_family,
)
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole

EMAIL_UNIQUE_INDEX = "uq_users_email_lower"

_users = User.__table__


class RoleMissingError(RuntimeError):
    """Reference role rows are missing: run `python -m app.seeds base`."""


@dataclass(frozen=True)
class IssuedSession:
    access: AccessToken
    refresh_token: str = field(repr=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _refresh_ttl() -> timedelta:
    return timedelta(days=get_settings().refresh_token_ttl_days)


async def _customer_role_id(session: AsyncSession) -> uuid.UUID:
    role_id = await session.scalar(select(Role.id).where(Role.name == RoleName.CUSTOMER.value))
    if role_id is None:
        raise RoleMissingError("role 'customer' is missing")
    return role_id


def _is_email_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == EMAIL_UNIQUE_INDEX


async def register(session: AsyncSession, data: RegisterRequest) -> IssuedSession:
    if await session.scalar(select(User.id).where(func.lower(User.email) == data.email)):
        raise errors.email_already_exists()
    role_id = await _customer_role_id(session)
    password_hash = await run_in_threadpool(hash_password, data.password)
    now = _now()
    try:
        user_id = await session.scalar(
            insert(User)
            .values(
                email=data.email,
                password_hash=password_hash,
                full_name=data.full_name,
                phone=data.phone,
                preferred_language=data.preferred_language,
            )
            .returning(User.id)
        )
    except IntegrityError as exc:
        # A concurrent registration committed the same email first.
        await session.rollback()
        if _is_email_conflict(exc):
            raise errors.email_already_exists() from None
        raise
    assert user_id is not None  # noqa: S101 - RETURNING always yields the id
    await session.execute(insert(UserRole).values(user_id=user_id, role_id=role_id))
    _, raw_refresh = await create_family(session, user_id, now=now, ttl=_refresh_ttl())
    await session.commit()
    return IssuedSession(create_access_token(user_id, now=now), raw_refresh)


async def login(session: AsyncSession, email: str, password: str) -> IssuedSession:
    """Wrong password, unknown email and inactive account look the same."""
    row = (
        await session.execute(
            select(_users.c.id, _users.c.password_hash, _users.c.is_active).where(
                func.lower(_users.c.email) == email
            )
        )
    ).one_or_none()
    if row is None or row.password_hash is None:
        await run_in_threadpool(verify_dummy_password, password)
        raise errors.invalid_credentials()
    if not await run_in_threadpool(verify_password, row.password_hash, password):
        raise errors.invalid_credentials()
    if not row.is_active:
        raise errors.invalid_credentials()

    # DEC-143: lock the user (users -> refresh_tokens order) and re-check
    # is_active from this locking read only, so a deactivation committed in
    # the meantime can never be followed by a new refresh family.
    if not await lock_user(session, row.id):
        await session.rollback()
        raise errors.invalid_credentials()
    # The password may have been changed between the check and the lock:
    # the verified hash must still be the stored one (values under the lock
    # only, DEC-140), otherwise the rehash below could restore an old password.
    locked_hash = await session.scalar(select(_users.c.password_hash).where(_users.c.id == row.id))
    if locked_hash != row.password_hash:
        await session.rollback()
        raise errors.invalid_credentials()

    now = _now()
    if password_needs_rehash(row.password_hash):
        new_hash = await run_in_threadpool(hash_password, password)
        await session.execute(
            update(_users).where(_users.c.id == row.id).values(password_hash=new_hash)
        )
    _, raw_refresh = await create_family(session, row.id, now=now, ttl=_refresh_ttl())
    await session.commit()
    return IssuedSession(create_access_token(row.id, now=now), raw_refresh)


async def refresh(session: AsyncSession, raw_token: str | None) -> IssuedSession:
    now = _now()
    try:
        outcome = await refresh_in_transaction(session, raw_token, now=now, ttl=_refresh_ttl())
    except RefreshRotationConflict:
        await session.rollback()  # nothing is revoked on this path (DEC-140)
        raise errors.invalid_refresh_token() from None
    # Revocations of a refused refresh must be durable before the 401.
    await session.commit()
    if outcome.status is not RefreshStatus.OK:
        raise errors.invalid_refresh_token()
    assert outcome.user_id is not None and outcome.new_token is not None  # noqa: S101
    return IssuedSession(create_access_token(outcome.user_id, now=now), outcome.new_token)


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    """Revoke the token's family if the token row exists; always succeeds."""
    if raw_token and len(raw_token) <= MAX_REFRESH_TOKEN_LENGTH:
        token_hash = hash_refresh_token(raw_token)
        owner_id = await find_token_owner(session, token_hash)
        if owner_id is not None:
            await lock_user(session, owner_id)
            token = await lock_token(session, token_hash)
            if token is not None:
                await revoke_family(session, token.family_id, now=_now())
    await session.commit()


async def change_password(
    session: AsyncSession, user_id: uuid.UUID, current_password: str, new_password: str
) -> None:
    # Lock the user first; use only values read under this lock.
    is_active = await lock_user(session, user_id)
    if not is_active:
        await session.rollback()
        raise errors.unauthorized()
    password_hash = await session.scalar(
        select(_users.c.password_hash).where(_users.c.id == user_id)
    )
    if password_hash is None:
        # Telegram-only account (DEC-142): there is no password to change.
        await session.rollback()
        raise errors.password_not_set()
    if not await run_in_threadpool(verify_password, password_hash, current_password):
        await session.rollback()
        raise errors.current_password_invalid()
    new_hash = await run_in_threadpool(hash_password, new_password)
    now = _now()
    await session.execute(
        update(_users)
        .where(_users.c.id == user_id)
        .values(password_hash=new_hash, must_change_password=False)
    )
    await revoke_all_for_user(session, user_id, now=now)
    await session.commit()


async def add_credentials(
    session: AsyncSession, user_id: uuid.UUID, email: str, password: str
) -> None:
    """Set email and password of a Telegram-only account (DEC-142).

    Only while `email IS NULL`: one atomic `UPDATE ... WHERE email IS NULL`
    that must change exactly one row. A concurrent request for the same user
    waits for this row lock, re-checks the condition and changes nothing; a
    concurrent use of the same email by another account fails on the unique
    index. Refresh families are not touched: a Telegram-only account has
    none (the Mini App uses no refresh cookie, DEC-142).
    """
    current = (
        await session.execute(
            select(_users.c.email, _users.c.is_active).where(_users.c.id == user_id)
        )
    ).one_or_none()
    if current is None or not current.is_active:
        raise errors.unauthorized()
    if current.email is not None:
        raise errors.credentials_already_set()
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise errors.email_already_exists()
    password_hash = await run_in_threadpool(hash_password, password)
    try:
        updated = await session.scalar(
            update(_users)
            .where(_users.c.id == user_id, _users.c.email.is_(None), _users.c.is_active)
            .values(email=email, password_hash=password_hash)
            .returning(_users.c.id)
        )
    except IntegrityError as exc:
        # Another account committed the same email first.
        await session.rollback()
        if _is_email_conflict(exc):
            raise errors.email_already_exists() from None
        raise
    if updated is None:
        # Changed meanwhile: credentials were set or the account was deactivated.
        await session.rollback()
        row = (
            await session.execute(
                select(_users.c.email, _users.c.is_active).where(_users.c.id == user_id)
            )
        ).one_or_none()
        if row is None or not row.is_active:
            raise errors.unauthorized()
        raise errors.credentials_already_set()
    await session.commit()
