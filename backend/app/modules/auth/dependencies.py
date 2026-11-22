"""FastAPI dependencies for authentication and authorization.

- The access JWT carries only the user id; roles, `is_active` and
  `must_change_password` are read from the database on every request
  (DEC-66, DEC-140).
- While `must_change_password` is set, only `/auth/me`,
  `/auth/password/change`, `/auth/logout` and `/auth/refresh` are allowed
  (DEC-28, DEC-140). The last two do not use the access token at all.
- CSRF for cookie-based operations: exact `Origin` match with
  CSRF_TRUSTED_ORIGINS and header `X-CSRF-Protection: 1` (DEC-68, DEC-140).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import InvalidAccessTokenError, decode_access_token
from app.db.session import get_session
from app.modules.auth import errors
from app.modules.users.models import Role, User, UserRole

CSRF_HEADER = "X-CSRF-Protection"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str | None
    full_name: str
    phone: str | None
    preferred_language: str
    roles: frozenset[str]
    must_change_password: bool
    has_password: bool


async def _load_user(session: AsyncSession, user_id: uuid.UUID) -> CurrentUser | None:
    row = (
        await session.execute(
            select(
                User.id,
                User.email,
                User.full_name,
                User.phone,
                User.preferred_language,
                User.is_active,
                User.must_change_password,
                User.password_hash.is_not(None).label("has_password"),
            ).where(User.id == user_id)
        )
    ).one_or_none()
    if row is None or not row.is_active:
        return None
    roles = await session.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return CurrentUser(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        phone=row.phone,
        preferred_language=row.preferred_language,
        roles=frozenset(roles.all()),
        must_change_password=row.must_change_password,
        has_password=row.has_password,
    )


async def load_current_user(session: AsyncSession, user_id: uuid.UUID) -> CurrentUser | None:
    """Current state of an active user from the database, else None."""
    return await _load_user(session, user_id)


async def get_authenticated_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Valid access token of an existing active user; ignores
    `must_change_password` (only for the routes allowed while it is set)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise errors.unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessTokenError:
        raise errors.unauthorized() from None
    user = await _load_user(session, user_id)
    if user is None:
        raise errors.unauthorized()
    return user


async def get_optional_user_language(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str | None:
    """`preferred_language` of an authenticated active user, else None.

    For public endpoints: a missing or invalid token is not an error here.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessTokenError:
        return None
    return await session.scalar(
        select(User.preferred_language).where(User.id == user_id, User.is_active)
    )


async def get_current_user(
    user: Annotated[CurrentUser, Depends(get_authenticated_user)],
) -> CurrentUser:
    """Default dependency for protected routes."""
    if user.must_change_password:
        raise errors.password_change_required()
    return user


def require_roles(*roles: str) -> Callable[..., Awaitable[CurrentUser]]:
    """Allow the request if the user has at least one of `roles` (DEC-23)."""
    allowed = frozenset(roles)
    if not allowed:
        raise ValueError("require_roles needs at least one role")

    async def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if user.roles.isdisjoint(allowed):
            raise errors.forbidden()
        return user

    return _dependency


async def csrf_protect(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin not in get_settings().csrf_trusted_origins:
        raise errors.csrf_failed()
    if request.headers.get(CSRF_HEADER) != "1":
        raise errors.csrf_failed()
