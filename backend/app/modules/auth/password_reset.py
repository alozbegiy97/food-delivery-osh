"""Password reset by e-mail (DEC-108, DEC-140; API_SPECIFICATION.md §2.1).

- forgot: for an existing active user, earlier unused tokens are marked used
  and a new one (32 random bytes, SHA-256 stored, 30 minutes) is created.
  The caller always answers 202 and sends the mail after the response.
- reset: a valid token sets the new Argon2id hash, `used_at`,
  `must_change_password = false` and revokes every refresh family of the
  user, all in one transaction. Anything else is 400 INVALID_OR_EXPIRED_TOKEN.
- Lock order: users first (`lock_user`), then the token row, then
  refresh_tokens (DEC-140).
- Tokens and links are never logged.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.mailer import OutgoingEmail
from app.core.security import hash_password
from app.modules.auth.emails import password_reset_email
from app.modules.auth.refresh_sessions import lock_user, revoke_all_for_user
from app.modules.users.models import PasswordResetToken, User

RESET_TOKEN_BYTES = 32
MAX_RESET_TOKEN_LENGTH = 128

_users = User.__table__
_tokens = PasswordResetToken.__table__


def invalid_or_expired_token() -> AppError:
    return AppError(400, "INVALID_OR_EXPIRED_TOKEN", "Ссылка недействительна или устарела")


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResetMail:
    email: OutgoingEmail = field(repr=False)


async def request_reset(session: AsyncSession, email: str) -> ResetMail | None:
    """Create a reset token for an existing active user; None otherwise."""
    settings = get_settings()
    row = (
        await session.execute(
            select(_users.c.id, _users.c.email, _users.c.preferred_language).where(
                func.lower(_users.c.email) == email
            )
        )
    ).one_or_none()
    if row is None or row.email is None:
        return None
    if not await lock_user(session, row.id):
        await session.rollback()
        return None

    now = datetime.now(UTC)
    await session.execute(
        update(_tokens)
        .where(_tokens.c.user_id == row.id, _tokens.c.used_at.is_(None))
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    ttl = settings.password_reset_token_ttl_minutes
    await session.execute(
        insert(_tokens).values(
            user_id=row.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(minutes=ttl),
        )
    )
    await session.commit()
    link = f"{settings.frontend_base_url}/reset-password?token={raw_token}"
    return ResetMail(password_reset_email(row.email, row.preferred_language, link, ttl))


async def reset_password(session: AsyncSession, raw_token: str, new_password: str) -> None:
    if not raw_token or len(raw_token) > MAX_RESET_TOKEN_LENGTH:
        raise invalid_or_expired_token()
    token_hash = hash_reset_token(raw_token)
    user_id = await session.scalar(
        select(_tokens.c.user_id).where(_tokens.c.token_hash == token_hash)
    )
    if user_id is None:
        raise invalid_or_expired_token()

    is_active = await lock_user(session, user_id)
    token = (
        await session.execute(
            select(_tokens.c.id, _tokens.c.expires_at, _tokens.c.used_at)
            .where(_tokens.c.token_hash == token_hash)
            .with_for_update()
        )
    ).one_or_none()
    now = datetime.now(UTC)
    if not is_active or token is None or token.used_at is not None or token.expires_at <= now:
        await session.rollback()
        raise invalid_or_expired_token()

    new_hash = await run_in_threadpool(hash_password, new_password)
    await session.execute(
        update(_users)
        .where(_users.c.id == user_id)
        .values(password_hash=new_hash, must_change_password=False)
    )
    await session.execute(update(_tokens).where(_tokens.c.id == token.id).values(used_at=now))
    await revoke_all_for_user(session, user_id, now=now)
    await session.commit()
