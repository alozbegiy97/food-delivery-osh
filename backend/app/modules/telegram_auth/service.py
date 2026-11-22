"""Telegram Mini App login, registration and linking (API §2.3).

DEC-142, DEC-152 п. 2-4, 8, 10, DEC-154. Every operation returns only an
access token (no refresh cookie, no CSRF). Order inside each operation:
rate limit (router) -> schema -> TELEGRAM_DISABLED -> `initData` -> rest.

Transactions and locks:

- `login` reads the link and the user without locks; the only possible
  write is raising `telegram_links.is_active` to TRUE (one row; no advisory,
  no `users` lock): it neither creates nor deletes a link.
- `register` and `link` run `SET LOCAL lock_timeout = '5s'` (U1) and lock in
  the order advisory(Telegram ID) -> `users` FOR NO KEY UPDATE ->
  `telegram_links` (DEC-152 п. 3). A lock timeout (SQLSTATE 55P03 only)
  rolls back and answers `409 TELEGRAM_BUSY`; deadlocks and other database
  errors are not converted.
- Argon2 runs in a worker thread and never while a lock is held.
- Unique constraints of `telegram_links` stay the last line of defence: a
  violation rolls back completely and maps to the same 409 codes.
- Nothing here logs `initData`, passwords, tokens or the bot token.
"""

import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import (
    AccessToken,
    create_access_token,
    verify_dummy_password,
    verify_password,
)
from app.modules.auth import errors as auth_errors
from app.modules.auth.refresh_sessions import lock_user
from app.modules.auth.service import RoleMissingError
from app.modules.notifications.models import TelegramLink
from app.modules.telegram_auth import errors
from app.modules.telegram_auth.init_data import (
    InvalidInitData,
    VerifiedTelegramUser,
    verify_init_data,
)
from app.modules.telegram_auth.locks import is_lock_timeout, lock_telegram_id, set_lock_timeout
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole

FULL_NAME_MAX_LENGTH = 150
FALLBACK_NAME = "Telegram"
SUPPORTED_LANGUAGES = frozenset({"ru", "ky", "uz"})
DEFAULT_LANGUAGE = "ru"

CHAT_ID_UNIQUE = "uq_telegram_links_telegram_chat_id"
USER_ID_UNIQUE = "uq_telegram_links_user_id"

_users = User.__table__
_links = TelegramLink.__table__


@dataclass(frozen=True)
class _Link:
    id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool


# --------------------------------------------------------------------------
# Rules taken from the verified initData (DEC-142, DEC-154 п. 7)
# --------------------------------------------------------------------------


def _clean_name(value: str) -> str:
    """Control characters removed, stripped, at most 150 code points, stripped."""
    without_controls = "".join(ch for ch in value if unicodedata.category(ch) != "Cc")
    return without_controls.strip()[:FULL_NAME_MAX_LENGTH].strip()


def full_name_from(tg: VerifiedTelegramUser) -> str:
    """DEC-142: `first_name last_name`, else `username`, else `Telegram`."""
    parts = [part for part in (tg.first_name, tg.last_name) if part]
    name = _clean_name(" ".join(parts))
    if not name and tg.username:
        name = _clean_name(tg.username)
    return name or FALLBACK_NAME


def language_from(tg: VerifiedTelegramUser) -> str:
    """DEC-154 п. 7: exactly `ru`/`ky`/`uz`, anything else -> `ru`."""
    code = tg.language_code
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


# --------------------------------------------------------------------------
# Shared steps
# --------------------------------------------------------------------------


def verified_user(init_data: str) -> VerifiedTelegramUser:
    """TELEGRAM_DISABLED first, then the initData verification (401)."""
    settings = get_settings()
    bot_token = settings.telegram_bot_token_value
    if bot_token is None:
        raise errors.telegram_disabled()
    try:
        return verify_init_data(
            init_data,
            bot_token=bot_token,
            now=int(time.time()),
            max_age_seconds=settings.telegram_webapp_auth_max_age_seconds,
            clock_skew_seconds=settings.telegram_webapp_clock_skew_seconds,
            max_length=settings.telegram_webapp_init_data_max_length,
        )
    except InvalidInitData:
        raise errors.invalid_telegram_auth() from None


async def _find_link(
    session: AsyncSession, *, telegram_id: int | None = None, user_id: uuid.UUID | None = None
) -> _Link | None:
    query = select(_links.c.id, _links.c.user_id, _links.c.is_active)
    if telegram_id is not None:
        query = query.where(_links.c.telegram_chat_id == telegram_id)
    else:
        query = query.where(_links.c.user_id == user_id)
    row = (await session.execute(query)).one_or_none()
    return None if row is None else _Link(row.id, row.user_id, row.is_active)


async def _is_customer(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists()
                .where(UserRole.user_id == user_id)
                .where(UserRole.role_id == Role.id)
                .where(Role.name == RoleName.CUSTOMER.value)
            )
        )
    )


async def _raise_write_permission(
    session: AsyncSession, link: _Link, tg: VerifiedTelegramUser
) -> None:
    """DEC-154 п. 3: true may raise is_active to TRUE; false never lowers it."""
    if tg.allows_write_to_pm and not link.is_active:
        await session.execute(
            update(_links).where(_links.c.id == link.id, ~_links.c.is_active).values(is_active=True)
        )


async def _login_linked(
    session: AsyncSession, link: _Link, tg: VerifiedTelegramUser
) -> AccessToken:
    """Login of an existing link (also `register` when the link exists)."""
    is_active = await session.scalar(select(_users.c.is_active).where(_users.c.id == link.user_id))
    if not is_active:
        await session.rollback()
        raise errors.invalid_telegram_auth()
    if not await _is_customer(session, link.user_id):
        await session.rollback()
        raise auth_errors.forbidden()
    await _raise_write_permission(session, link, tg)
    await session.commit()
    return create_access_token(link.user_id)


def _new_link_values(user_id: uuid.UUID, tg: VerifiedTelegramUser) -> dict[str, object]:
    return {
        "user_id": user_id,
        "telegram_chat_id": tg.telegram_id,
        "telegram_username": tg.username,
        "is_active": tg.allows_write_to_pm,
        "linked_at": datetime.now(UTC),
    }


def _violated_constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp
# --------------------------------------------------------------------------


async def login(session: AsyncSession, init_data: str) -> AccessToken:
    tg = verified_user(init_data)
    link = await _find_link(session, telegram_id=tg.telegram_id)
    if link is None:
        raise errors.telegram_not_linked()  # nothing is written
    return await _login_linked(session, link, tg)


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp/register
# --------------------------------------------------------------------------


async def register(session: AsyncSession, init_data: str) -> AccessToken:
    tg = verified_user(init_data)
    try:
        return await _register_locked(session, tg)
    except IntegrityError as exc:
        # Only reachable if a link appeared despite the advisory lock (e.g. a
        # future code path without it): roll back completely and answer as
        # for the existing link.
        await session.rollback()
        if _violated_constraint(exc) != CHAT_ID_UNIQUE:
            raise
        link = await _find_link(session, telegram_id=tg.telegram_id)
        if link is None:
            raise
        return await _login_linked(session, link, tg)
    except DBAPIError as exc:
        if is_lock_timeout(exc):
            await session.rollback()
            raise errors.telegram_busy() from None
        raise


async def _register_locked(session: AsyncSession, tg: VerifiedTelegramUser) -> AccessToken:
    await set_lock_timeout(session)
    await lock_telegram_id(session, tg.telegram_id)
    link = await _find_link(session, telegram_id=tg.telegram_id)
    if link is not None:
        return await _login_linked(session, link, tg)  # no second account

    role_id = await session.scalar(select(Role.id).where(Role.name == RoleName.CUSTOMER.value))
    if role_id is None:
        raise RoleMissingError("role 'customer' is missing")
    user_id = await session.scalar(
        insert(User)
        .values(
            email=None,
            password_hash=None,
            full_name=full_name_from(tg),
            phone=None,
            preferred_language=language_from(tg),
        )
        .returning(User.id)
    )
    assert user_id is not None  # noqa: S101 - RETURNING always yields the id
    await session.execute(insert(UserRole).values(user_id=user_id, role_id=role_id))
    await session.execute(insert(TelegramLink).values(**_new_link_values(user_id, tg)))
    await session.commit()
    return create_access_token(user_id)


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp/link
# --------------------------------------------------------------------------


async def link(session: AsyncSession, init_data: str, email: str, password: str) -> AccessToken:
    tg = verified_user(init_data)  # before the password (API §2.3)

    # Credentials exactly as /auth/login: an account without email is not
    # found, an unknown email spends a dummy Argon2 check, wrong password and
    # inactive account give the same 401 (DEC-103, DEC-152 п. 2.3).
    row = (
        await session.execute(
            select(_users.c.id, _users.c.password_hash, _users.c.is_active).where(
                func.lower(_users.c.email) == email
            )
        )
    ).one_or_none()
    if row is None or row.password_hash is None:
        await run_in_threadpool(verify_dummy_password, password)
        raise auth_errors.invalid_credentials()
    if not await run_in_threadpool(verify_password, row.password_hash, password):
        raise auth_errors.invalid_credentials()
    if not row.is_active:
        raise auth_errors.invalid_credentials()
    if not await _is_customer(session, row.id):  # first check (DEC-154 п. 5)
        raise auth_errors.forbidden()
    # End the read-only transaction: the locking one starts clean.
    await session.rollback()

    try:
        return await _link_locked(session, tg, row.id, row.password_hash)
    except IntegrityError as exc:
        await session.rollback()
        constraint = _violated_constraint(exc)
        if constraint == CHAT_ID_UNIQUE:
            raise errors.telegram_already_linked() from None
        if constraint == USER_ID_UNIQUE:
            raise errors.account_already_linked() from None
        raise
    except DBAPIError as exc:
        if is_lock_timeout(exc):
            await session.rollback()
            raise errors.telegram_busy() from None
        raise


async def _link_locked(
    session: AsyncSession, tg: VerifiedTelegramUser, user_id: uuid.UUID, verified_hash: str
) -> AccessToken:
    await set_lock_timeout(session)
    await lock_telegram_id(session, tg.telegram_id)
    # users FOR NO KEY UPDATE; every value below is read under this lock.
    if not await lock_user(session, user_id):  # deactivated or deleted meanwhile
        await session.rollback()
        raise auth_errors.invalid_credentials()
    locked_hash = await session.scalar(select(_users.c.password_hash).where(_users.c.id == user_id))
    if locked_hash != verified_hash:  # password changed meanwhile (DEC-143)
        await session.rollback()
        raise auth_errors.invalid_credentials()
    if not await _is_customer(session, user_id):  # second check (DEC-154 п. 5)
        await session.rollback()
        raise auth_errors.forbidden()

    by_telegram = await _find_link(session, telegram_id=tg.telegram_id)
    if by_telegram is not None:
        if by_telegram.user_id != user_id:
            await session.rollback()
            raise errors.telegram_already_linked()
        # Same pair: idempotent; only is_active may be raised (DEC-154 п. 3).
        await _raise_write_permission(session, by_telegram, tg)
        await session.commit()
        return create_access_token(user_id)
    if await _find_link(session, user_id=user_id) is not None:
        await session.rollback()
        raise errors.account_already_linked()

    await session.execute(insert(TelegramLink).values(**_new_link_values(user_id, tg)))
    await session.commit()
    return create_access_token(user_id)
