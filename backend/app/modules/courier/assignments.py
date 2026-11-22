"""Courier assignment by the administrator (API §9; DATABASE_SCHEMA.md §3.4,
§9.3; DEC-48…DEC-51, DEC-67, DEC-92, DEC-151).

Lock order (DEC-151 п. 6): `orders` (`FOR UPDATE`) → `users` of the courier
(`FOR SHARE`) → `courier_profiles` (`FOR UPDATE`) → `courier_assignments`.
`FOR SHARE` on `users` conflicts with the `FOR NO KEY UPDATE` of the staff
operations (deactivation, role change), so an assignment and a deactivation
of the same courier never interleave. Automatic assignment locks the rows of
all candidates in `user_id` order. Nothing here locks `orders` after `users`
or `courier_profiles`.
"""

import uuid

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.courier.schemas import (
    AssignmentOut,
    CourierList,
    CourierOut,
    CourierSettingsIn,
)
from app.modules.delivery.enums import AssignmentStatus, AssignmentType
from app.modules.delivery.models import CourierAssignment
from app.modules.orders.enums import DeliveryType, OrderStatus
from app.modules.orders.models import Order
from app.modules.users.enums import RoleName
from app.modules.users.models import CourierProfile, Role, User, UserRole

# DEC-48: a courier can be assigned from `confirmed` up to (not including)
# `out_for_delivery`, and only to a delivery order.
ASSIGNABLE_STATUSES = (
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
)


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def invalid_status() -> AppError:
    return AppError(409, "INVALID_STATUS_TRANSITION", "Переход статуса не разрешён")


def courier_not_available() -> AppError:
    return AppError(409, "COURIER_NOT_AVAILABLE", "Курьер недоступен")


def no_courier_available() -> AppError:
    return AppError(409, "NO_COURIER_AVAILABLE", "Нет доступного курьера")


def has_courier_role(user_id_column):  # noqa: ANN001, ANN201 - SQL expression
    return exists().where(
        UserRole.user_id == user_id_column,
        UserRole.role_id == Role.id,
        Role.name == RoleName.COURIER.value,
    )


def active_count(user_id_column):  # noqa: ANN001, ANN201 - scalar subquery
    return (
        select(func.count())
        .select_from(CourierAssignment)
        .where(
            CourierAssignment.courier_id == user_id_column,
            CourierAssignment.status == AssignmentStatus.ACTIVE,
        )
        .scalar_subquery()
    )


def needs_courier():  # noqa: ANN201 - SQL expression
    """A delivery order that can get a courier but has no active one."""
    return (
        (Order.delivery_type == DeliveryType.DELIVERY)
        & Order.status.in_(ASSIGNABLE_STATUSES)
        & ~exists().where(
            CourierAssignment.order_id == Order.id,
            CourierAssignment.status == AssignmentStatus.ACTIVE,
        )
    )


# --------------------------------------------------------------------------
# Couriers
# --------------------------------------------------------------------------


def _courier_query():  # noqa: ANN202 - Select
    return (
        select(
            User.id,
            User.full_name,
            User.phone,
            User.email,
            User.is_active,
            CourierProfile.is_available,
            CourierProfile.max_active_orders,
            active_count(User.id).label("active"),
        )
        .join(CourierProfile, CourierProfile.user_id == User.id)
        .where(has_courier_role(User.id))
    )


def _courier_out(row) -> CourierOut:  # noqa: ANN001 - Row
    return CourierOut(
        user_id=row.id,
        full_name=row.full_name,
        phone=row.phone,
        email=row.email,
        is_active=row.is_active,
        is_available=row.is_available,
        max_active_orders=row.max_active_orders,
        active_assignments=int(row.active),
    )


async def list_couriers(session: AsyncSession) -> CourierList:
    rows = await session.execute(_courier_query().order_by(User.full_name, User.id))
    return CourierList(items=[_courier_out(row) for row in rows])


async def get_courier(session: AsyncSession, user_id: uuid.UUID) -> CourierOut:
    row = (await session.execute(_courier_query().where(User.id == user_id))).one_or_none()
    if row is None:
        raise not_found()
    return _courier_out(row)


async def update_courier(
    session: AsyncSession, user_id: uuid.UUID, payload: CourierSettingsIn
) -> CourierOut:
    """Availability and `max_active_orders` (1–10, DEC-151 п. 2).

    Locks only the profile row. Lowering the limit below the number of
    active assignments keeps them; only new assignments are refused."""
    locked = await session.scalar(
        select(CourierProfile.user_id)
        .where(CourierProfile.user_id == user_id, has_courier_role(CourierProfile.user_id))
        .with_for_update(of=CourierProfile)
    )
    if locked is None:
        raise not_found()
    values: dict[str, object] = {}
    if payload.is_available is not None:
        values["is_available"] = payload.is_available
    if payload.max_active_orders is not None:
        values["max_active_orders"] = payload.max_active_orders
    await session.execute(
        update(CourierProfile).where(CourierProfile.user_id == user_id).values(**values)
    )
    await session.commit()
    return await get_courier(session, user_id)


# --------------------------------------------------------------------------
# Assignments of an order
# --------------------------------------------------------------------------


async def order_assignments(session: AsyncSession, order_id: uuid.UUID) -> list[AssignmentOut]:
    courier = User.__table__.alias("courier")
    assigner = User.__table__.alias("assigner")
    rows = await session.execute(
        select(
            CourierAssignment,
            courier.c.full_name.label("courier_name"),
            courier.c.phone.label("courier_phone"),
            assigner.c.full_name.label("assigner_name"),
        )
        .join(courier, courier.c.id == CourierAssignment.courier_id)
        .outerjoin(assigner, assigner.c.id == CourierAssignment.assigned_by)
        .where(CourierAssignment.order_id == order_id)
        .order_by(CourierAssignment.assigned_at, CourierAssignment.id)
    )
    return [
        AssignmentOut(
            id=a.id,
            courier_id=a.courier_id,
            courier_name=courier_name,
            courier_phone=courier_phone,
            assignment_type=a.assignment_type,
            status=a.status,
            assigned_by_name=assigner_name,
            assigned_at=a.assigned_at,
            accepted_at=a.accepted_at,
            declined_at=a.declined_at,
            decline_reason=a.decline_reason,
            completed_at=a.completed_at,
        )
        for a, courier_name, courier_phone, assigner_name in rows
    ]


async def _check_assignable(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Under the order lock taken by the caller: DEC-48."""
    order = (
        await session.execute(select(Order.status, Order.delivery_type).where(Order.id == order_id))
    ).one()
    if order.delivery_type != DeliveryType.DELIVERY or order.status not in ASSIGNABLE_STATUSES:
        raise invalid_status()


async def _active_assignment(session: AsyncSession, order_id: uuid.UUID):  # noqa: ANN202
    return (
        await session.execute(
            select(CourierAssignment.id, CourierAssignment.courier_id).where(
                CourierAssignment.order_id == order_id,
                CourierAssignment.status == AssignmentStatus.ACTIVE,
            )
        )
    ).one_or_none()


async def _create(
    session: AsyncSession,
    order_id: uuid.UUID,
    courier_id: uuid.UUID,
    *,
    assignment_type: AssignmentType,
    assigned_by: uuid.UUID | None,
    replaced: uuid.UUID | None,
) -> None:
    if replaced is not None:
        # DEC-51: the previous active assignment is cancelled in the same transaction.
        await session.execute(
            update(CourierAssignment)
            .where(CourierAssignment.id == replaced)
            .values(status=AssignmentStatus.CANCELLED.value)
        )
    await session.execute(
        insert(CourierAssignment).values(
            order_id=order_id,
            courier_id=courier_id,
            assigned_by=assigned_by,
            assignment_type=assignment_type.value,
            status=AssignmentStatus.ACTIVE.value,
            assigned_at=func.now(),
        )
    )


async def assign(
    session: AsyncSession, order_id: uuid.UUID, courier_id: uuid.UUID, *, admin_id: uuid.UUID
) -> None:
    """Manual assignment or reassignment (DEC-51, DEC-67, DEC-151 п. 4).

    The caller has locked the order row. Commits."""
    await _check_assignable(session, order_id)
    current = await _active_assignment(session, order_id)
    if current is not None and current.courier_id == courier_id:
        await session.rollback()  # DEC-151 п. 4: the same courier, nothing changes
        return

    # users (FOR SHARE): the role and is_active cannot change until commit.
    user = (
        await session.execute(
            select(User.id, User.is_active).where(User.id == courier_id).with_for_update(read=True)
        )
    ).one_or_none()
    if user is None or not user.is_active:
        raise courier_not_available()
    if not await session.scalar(select(has_courier_role(courier_id))):
        raise courier_not_available()
    # courier_profiles (FOR UPDATE): availability and the limit (DEC-67).
    profile = (
        await session.execute(
            select(CourierProfile.is_available, CourierProfile.max_active_orders)
            .where(CourierProfile.user_id == courier_id)
            .with_for_update()
        )
    ).one_or_none()
    if profile is None or not profile.is_available:
        raise courier_not_available()
    if int(await session.scalar(select(active_count(courier_id))) or 0) >= (
        profile.max_active_orders
    ):
        raise courier_not_available()

    await _create(
        session,
        order_id,
        courier_id,
        assignment_type=AssignmentType.MANUAL,
        assigned_by=admin_id,
        replaced=current.id if current else None,
    )
    await session.commit()


async def auto_assign(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Automatic assignment (DEC-49, DEC-50, DEC-92, DEC-151 п. 3–4).

    The caller has locked the order row. Commits."""
    await _check_assignable(session, order_id)
    if await _active_assignment(session, order_id) is not None:
        await session.rollback()  # DEC-151 п. 4: the current assignment stays
        return

    declined = exists().where(
        CourierAssignment.order_id == order_id,
        CourierAssignment.courier_id == User.id,
        CourierAssignment.status == AssignmentStatus.DECLINED,
    )
    candidates = list(
        await session.scalars(
            select(User.id)
            .join(CourierProfile, CourierProfile.user_id == User.id)
            .where(
                User.is_active,
                CourierProfile.is_available,
                has_courier_role(User.id),
                ~declined,
            )
            .order_by(User.id)
        )
    )
    if not candidates:
        raise no_courier_available()
    # The same list, in user_id order: users FOR SHARE, then the profiles.
    await session.execute(
        select(User.id).where(User.id.in_(candidates)).order_by(User.id).with_for_update(read=True)
    )
    await session.execute(
        select(CourierProfile.user_id)
        .where(CourierProfile.user_id.in_(candidates))
        .order_by(CourierProfile.user_id)
        .with_for_update()
    )
    # Re-checked under the locks; the order of DEC-151 п. 3.
    last_assigned = (
        select(func.max(CourierAssignment.assigned_at))
        .where(CourierAssignment.courier_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    active = active_count(User.id)
    chosen = await session.scalar(
        select(User.id)
        .join(CourierProfile, CourierProfile.user_id == User.id)
        .where(
            User.id.in_(candidates),
            User.is_active,
            CourierProfile.is_available,
            has_courier_role(User.id),
            ~declined,
            active < CourierProfile.max_active_orders,
        )
        .order_by(active.asc(), last_assigned.asc().nulls_first(), User.id.asc())
        .limit(1)
    )
    if chosen is None:
        raise no_courier_available()
    await _create(
        session,
        order_id,
        chosen,
        assignment_type=AssignmentType.AUTOMATIC,
        assigned_by=None,  # automatic assignment (§9.3)
        replaced=None,
    )
    await session.commit()
