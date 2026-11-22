"""Staff management (API §9 "Staff"; DEC-23, DEC-27…DEC-29, DEC-62, DEC-66,
DEC-88, DEC-96, DEC-113, DEC-140, DEC-150).

- the list shows users with the roles `cook` and/or `courier`;
- only `cook` and `courier` are granted or removed here; other roles of the
  user (`admin`, `customer`) stay untouched; `admin` accounts are never
  deactivated or reactivated by this API (`409 ADMIN_ACCOUNT_PROTECTED`), so
  it can never leave the system without an active administrator;
- granting `courier` creates `courier_profiles` (DEC-27); removing it, or
  deactivating a courier, with active assignments -> `409
  COURIER_HAS_ACTIVE_ASSIGNMENTS` (DEC-29; assignments appear in stage 9);
- a new employee gets a temporary password and must change it (DEC-28);
- deactivation sets `is_active = false` and revokes every refresh session in
  the same transaction; reactivation restores access with the same password
  and roles. Both are idempotent. Lock order: users -> refresh_tokens
  (DEC-140).
"""

import math
import uuid
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.addresses.schemas import Pagination
from app.modules.auth import errors as auth_errors
from app.modules.auth.refresh_sessions import revoke_all_for_user
from app.modules.delivery.enums import AssignmentStatus
from app.modules.delivery.models import CourierAssignment
from app.modules.staff.schemas import StaffCreate, StaffList, StaffOut, StaffRolesUpdate
from app.modules.users.enums import RoleName
from app.modules.users.models import CourierProfile, Role, User, UserRole

STAFF_ROLES = (RoleName.COOK.value, RoleName.COURIER.value)


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def _protected() -> AppError:
    return AppError(
        409,
        "ADMIN_ACCOUNT_PROTECTED",
        "API сотрудников не управляет административными аккаунтами",
    )


def _courier_busy() -> AppError:
    return AppError(
        409,
        "COURIER_HAS_ACTIVE_ASSIGNMENTS",
        "У курьера есть активные назначения",
    )


async def _role_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    return dict((await session.execute(select(Role.name, Role.id))).all())


async def _roles_of(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return sorted(
        await session.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
    )


async def _out(session: AsyncSession, user_id: uuid.UUID) -> StaffOut:
    user = await session.scalar(select(User).where(User.id == user_id))
    assert user is not None  # noqa: S101
    return StaffOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        roles=await _roles_of(session, user_id),
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


def _is_staff():  # noqa: ANN202 - SQL expression
    return exists().where(
        UserRole.user_id == User.id,
        UserRole.role_id.in_(select(Role.id).where(Role.name.in_(STAFF_ROLES))),
    )


async def list_staff(session: AsyncSession, *, page: int, page_size: int) -> StaffList:
    total = int(
        await session.scalar(select(func.count()).select_from(User).where(_is_staff())) or 0
    )
    ids = list(
        await session.scalars(
            select(User.id)
            .where(_is_staff())
            .order_by(User.is_active.desc(), User.full_name, User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return StaffList(
        items=[await _out(session, user_id) for user_id in ids],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def _lock_staff_user(
    session: AsyncSession, user_id: uuid.UUID, *, protect_admin: bool = False
) -> User:
    """Lock the user row (users -> refresh_tokens, DEC-140); only staff users.

    With `protect_admin` any user with the `admin` role -> 409, even one
    without staff roles (API §9: deactivate/reactivate, DEC-150)."""
    # FOR NO KEY UPDATE as DEC-140 requires (DEC-151 п. 6): conflicts with the
    # FOR SHARE of a courier assignment, not with FK key-share locks.
    user = await session.scalar(
        select(User).where(User.id == user_id).with_for_update(key_share=True)
    )
    if user is None:
        raise not_found()
    roles = set(await _roles_of(session, user_id))
    if protect_admin and RoleName.ADMIN.value in roles:
        raise _protected()
    if not roles & set(STAFF_ROLES):
        raise not_found()
    return user


async def _has_active_assignments(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    CourierAssignment.courier_id == user_id,
                    CourierAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        )
    )


async def _ensure_courier_profile(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        pg_insert(CourierProfile).values(user_id=user_id).on_conflict_do_nothing()
    )


async def create_staff(session: AsyncSession, payload: StaffCreate) -> StaffOut:
    if await session.scalar(select(User.id).where(func.lower(User.email) == payload.email)):
        raise auth_errors.email_already_exists()
    password_hash = await run_in_threadpool(hash_password, payload.temporary_password)
    try:
        user_id = await session.scalar(
            insert(User)
            .values(
                email=payload.email,
                password_hash=password_hash,
                full_name=payload.full_name,
                phone=payload.phone,
                must_change_password=True,  # DEC-28
            )
            .returning(User.id)
        )
    except IntegrityError:
        await session.rollback()
        raise auth_errors.email_already_exists() from None
    role_ids = await _role_ids(session)
    await session.execute(
        insert(UserRole), [{"user_id": user_id, "role_id": role_ids[r]} for r in payload.roles]
    )
    if RoleName.COURIER.value in payload.roles:
        await _ensure_courier_profile(session, user_id)  # DEC-27
    await session.commit()
    return await _out(session, user_id)


async def update_roles(
    session: AsyncSession, user_id: uuid.UUID, payload: StaffRolesUpdate
) -> StaffOut:
    await _lock_staff_user(session, user_id)
    current = set(await _roles_of(session, user_id))
    wanted = set(payload.roles)
    role_ids = await _role_ids(session)
    removed = (current & set(STAFF_ROLES)) - wanted
    added = wanted - current
    if RoleName.COURIER.value in removed and await _has_active_assignments(session, user_id):
        raise _courier_busy()  # DEC-29
    if removed:
        await session.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id.in_([role_ids[r] for r in removed]),
            )
        )
    if added:
        await session.execute(
            insert(UserRole), [{"user_id": user_id, "role_id": role_ids[r]} for r in added]
        )
    if RoleName.COURIER.value in added:
        await _ensure_courier_profile(session, user_id)
    await session.commit()
    return await _out(session, user_id)


async def deactivate(session: AsyncSession, user_id: uuid.UUID) -> StaffOut:
    user = await _lock_staff_user(session, user_id, protect_admin=True)
    roles = set(await _roles_of(session, user_id))
    if RoleName.COURIER.value in roles and await _has_active_assignments(session, user_id):
        raise _courier_busy()  # DEC-150: no deactivation, no revocation
    if user.is_active:
        await session.execute(update(User).where(User.id == user_id).values(is_active=False))
        await revoke_all_for_user(session, user_id, now=datetime.now(UTC))
        await session.commit()
    else:
        await session.rollback()  # idempotent: nothing to change
    return await _out(session, user_id)


async def reactivate(session: AsyncSession, user_id: uuid.UUID) -> StaffOut:
    user = await _lock_staff_user(session, user_id, protect_admin=True)
    if not user.is_active:
        # Password, roles and must_change_password stay as they were.
        await session.execute(update(User).where(User.id == user_id).values(is_active=True))
        await session.commit()
    else:
        await session.rollback()
    return await _out(session, user_id)
