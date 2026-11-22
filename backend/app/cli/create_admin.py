"""First administrator (DEC-88, DEC-113).

`create_first_admin` runs inside the caller's transaction:

1. transaction-level advisory lock (its own key, separate from the seed
   lock), so two parallel runs cannot both create a "first" admin;
2. refuse if any user already has the role `admin`;
3. refuse if the `admin` role row is missing (seed `base` creates it) or the
   e-mail is taken;
4. insert the user (Argon2id hash only, `must_change_password = false`) with
   the single role `admin`.

The password is never printed, logged or stored anywhere but as a hash.
"""

import uuid

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole

CREATE_ADMIN_LOCK_KEY = 0x0AD_0088


class CreateAdminError(Exception):
    """Expected refusal; the message is safe to show to the operator."""


async def create_first_admin(
    conn: AsyncConnection, *, email: str, full_name: str, password: str
) -> uuid.UUID:
    # Same field rules as registration (DEC-141) and the password policy (DEC-96).
    data = RegisterRequest(email=email, full_name=full_name, password=password)

    await conn.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"),
        {"key": CREATE_ADMIN_LOCK_KEY},
    )
    admin_role_id = await conn.scalar(select(Role.id).where(Role.name == RoleName.ADMIN.value))
    if admin_role_id is None:
        raise CreateAdminError(
            "Роль admin не найдена: сначала выполните `python -m app.seeds base`."
        )
    existing_admin = await conn.scalar(
        select(UserRole.user_id).where(UserRole.role_id == admin_role_id).limit(1)
    )
    if existing_admin is not None:
        raise CreateAdminError("Администратор уже существует: команда работает только один раз.")
    if await conn.scalar(select(User.id).where(func.lower(User.email) == data.email)):
        raise CreateAdminError("Пользователь с таким email уже существует.")

    password_hash = await run_in_threadpool(hash_password, data.password)
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=data.email,
            password_hash=password_hash,
            full_name=data.full_name,
            must_change_password=False,
        )
        .returning(User.id)
    )
    assert user_id is not None  # noqa: S101 - RETURNING always yields the id
    await conn.execute(insert(UserRole).values(user_id=user_id, role_id=admin_role_id))
    return user_id
