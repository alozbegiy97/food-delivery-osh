"""Own profile: `GET/PATCH /users/me` (API_SPECIFICATION.md §4, DEC-152 п. 9).

Only `full_name`, `phone` and `preferred_language` of the current user are
changed; the user id always comes from the access token, never from the
request. One `UPDATE` of the user's own row (no other locks).
"""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import errors
from app.modules.auth.dependencies import CurrentUser, load_current_user
from app.modules.users.models import User
from app.modules.users.schemas import ProfileUpdate


async def update_profile(
    session: AsyncSession, user: CurrentUser, payload: ProfileUpdate
) -> CurrentUser:
    changes = payload.model_dump(include=payload.model_fields_set)
    if not changes:
        return user
    updated: uuid.UUID | None = await session.scalar(
        update(User).where(User.id == user.id, User.is_active).values(**changes).returning(User.id)
    )
    if updated is None:
        # Deactivated after the request was authenticated.
        await session.rollback()
        raise errors.unauthorized()
    await session.commit()
    fresh = await load_current_user(session, user.id)
    if fresh is None:
        raise errors.unauthorized()
    return fresh
