"""Courier assignments under concurrency (stage 9; DEC-29, DEC-51, DEC-67,
DEC-150, DEC-151 п. 6; DATABASE_SCHEMA.md §9.3).

Real committed transactions on db-test (verified by `async_engine`): two
operations run at the same time through the services, each in its own
session, several rounds each. Checked: no `deadlock detected`, no hang (a
timeout), and the invariants (limit, one active assignment per order, no
inactive courier or courier without the role holding an active assignment).
Every row created here is deleted afterwards.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.admin_orders import service as admin_orders
from app.modules.admin_orders.schemas import StatusChange
from app.modules.courier import service as courier_service
from app.modules.courier.schemas import DeclineIn
from app.modules.delivery.models import CourierAssignment, Delivery
from app.modules.orders.models import Order
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.staff import service as staff
from app.modules.staff.schemas import StaffRolesUpdate
from app.modules.users.enums import RoleName
from app.modules.users.models import CourierProfile, Role, User, UserRole

pytestmark = pytest.mark.db

ROUNDS = 4
TIMEOUT = 30  # seconds; a deadlock or lock wait cycle would hit this or PG's detector


@dataclass
class World:
    engine: AsyncEngine
    admin_id: uuid.UUID
    customer_id: uuid.UUID
    cash_id: uuid.UUID
    role_ids: dict[str, uuid.UUID]
    users: list[uuid.UUID] = field(default_factory=list)
    orders: list[uuid.UUID] = field(default_factory=list)

    async def courier(self, *, limit: int = 1, available: bool = True) -> uuid.UUID:
        async with self.engine.begin() as conn:
            user_id = await conn.scalar(
                insert(User)
                .values(
                    email=f"cc-{uuid.uuid4().hex}@example.com",
                    password_hash="not-a-real-hash",
                    full_name="Concurrency courier",
                )
                .returning(User.id)
            )
            await conn.execute(
                insert(UserRole).values(
                    user_id=user_id, role_id=self.role_ids[RoleName.COURIER.value]
                )
            )
            await conn.execute(
                insert(CourierProfile).values(
                    user_id=user_id, is_available=available, max_active_orders=limit
                )
            )
        self.users.append(user_id)
        return user_id

    async def order(self, status: str = "confirmed") -> uuid.UUID:
        async with self.engine.begin() as conn:
            order_id = await conn.scalar(
                insert(Order)
                .values(
                    user_id=self.customer_id,
                    language_code="ru",
                    delivery_type="delivery",
                    status=status,
                    payment_method_code="cash",
                    subtotal=560,
                    delivery_fee=100,
                    total_amount=660,
                    customer_name="Concurrency",
                    customer_phone="+996700123456",
                    delivery_address_text="ул. Ленина, 1",
                    delivery_latitude="40.5300000",
                    delivery_longitude="72.8000000",
                )
                .returning(Order.id)
            )
            await conn.execute(insert(Delivery).values(order_id=order_id))
            await conn.execute(
                insert(Payment).values(
                    order_id=order_id,
                    payment_method_id=self.cash_id,
                    amount=660,
                    status="pending",
                    is_simulated=False,
                )
            )
        self.orders.append(order_id)
        return order_id

    async def assign_directly(
        self, order_id: uuid.UUID, courier_id: uuid.UUID, *, accepted: bool = False
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                insert(CourierAssignment).values(
                    order_id=order_id,
                    courier_id=courier_id,
                    assigned_by=self.admin_id,
                    assignment_type="manual",
                    assigned_at=func.now(),
                    accepted_at=func.now() if accepted else None,
                )
            )

    async def scalar(self, query):  # noqa: ANN001, ANN201
        async with self.engine.connect() as conn:
            return await conn.scalar(query)

    async def rows(self, query):  # noqa: ANN001, ANN201
        async with self.engine.connect() as conn:
            return (await conn.execute(query)).all()


@pytest.fixture
async def world(async_engine: AsyncEngine) -> AsyncIterator[World]:
    created_roles: list[uuid.UUID] = []
    created_method = False
    async with async_engine.begin() as conn:
        role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
        for name in (RoleName.COURIER.value, RoleName.ADMIN.value, RoleName.COOK.value):
            if name not in role_ids:
                role_ids[name] = await conn.scalar(
                    insert(Role).values(name=name).returning(Role.id)
                )
                created_roles.append(role_ids[name])
        cash_id = await conn.scalar(select(PaymentMethod.id).where(PaymentMethod.code == "cash"))
        if cash_id is None:
            created_method = True
            cash_id = await conn.scalar(
                insert(PaymentMethod).values(code="cash").returning(PaymentMethod.id)
            )
        admin_id, customer_id = [
            await conn.scalar(
                insert(User)
                .values(
                    email=f"cc-{uuid.uuid4().hex}@example.com",
                    password_hash="not-a-real-hash",
                    full_name=name,
                )
                .returning(User.id)
            )
            for name in ("Concurrency admin", "Concurrency customer")
        ]
        await conn.execute(
            insert(UserRole).values(user_id=admin_id, role_id=role_ids[RoleName.ADMIN.value])
        )
    data = World(async_engine, admin_id, customer_id, cash_id, role_ids)
    data.users += [admin_id, customer_id]
    try:
        yield data
    finally:
        async with async_engine.begin() as conn:
            await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            if data.orders:
                for table in (CourierAssignment, Payment, Delivery):
                    await conn.execute(delete(table).where(table.order_id.in_(data.orders)))
                await conn.execute(
                    delete(Order).where(Order.id.in_(data.orders))
                )  # history: CASCADE
            await conn.execute(
                delete(User).where(User.id.in_(data.users))
            )  # roles, profiles: CASCADE
            if created_roles:
                await conn.execute(delete(Role).where(Role.id.in_(created_roles)))
            if created_method:
                await conn.execute(delete(PaymentMethod).where(PaymentMethod.id == cash_id))


async def _run(engine: AsyncEngine, call: Callable[[AsyncSession], Awaitable[object]]) -> object:
    """One operation in its own session; AppError is a normal outcome."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            return await call(session)
        except AppError as exc:
            return exc


async def _together(engine: AsyncEngine, *calls: Callable[[AsyncSession], Awaitable[object]]):  # noqa: ANN202
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(_run(engine, c) for c in calls)), timeout=TIMEOUT
        )
    except DBAPIError as exc:  # pragma: no cover - would be the bug
        raise AssertionError(f"database error under concurrency: {exc}") from exc
    for result in results:
        assert not isinstance(result, DBAPIError), result
    return results


def _codes(results: list[object]) -> list[str | None]:
    return sorted((r.code if isinstance(r, AppError) else None) or "" for r in results)


async def _active(world: World, *, courier_id=None, order_id=None) -> int:  # noqa: ANN001
    query = (
        select(func.count())
        .select_from(CourierAssignment)
        .where(CourierAssignment.status == "active")
    )
    if courier_id is not None:
        query = query.where(CourierAssignment.courier_id == courier_id)
    if order_id is not None:
        query = query.where(CourierAssignment.order_id == order_id)
    return int(await world.scalar(query) or 0)


async def _two_assignments_respect_the_limit(world: World) -> None:
    courier = await world.courier(limit=1)
    first, second = await world.order(), await world.order()
    results = await _together(
        world.engine,
        lambda s: admin_orders.assign_courier(s, first, courier, admin_id=world.admin_id),
        lambda s: admin_orders.assign_courier(s, second, courier, admin_id=world.admin_id),
    )
    assert _codes(results) == ["", "COURIER_NOT_AVAILABLE"]
    assert await _active(world, courier_id=courier) == 1


async def test_two_assignments_respect_the_limit(world: World) -> None:
    for _ in range(ROUNDS):
        await _two_assignments_respect_the_limit(world)


async def _two_assignments_of_one_order_keep_one_active(world: World) -> None:
    a, b = await world.courier(limit=3), await world.courier(limit=3)
    order = await world.order()
    await _together(
        world.engine,
        lambda s: admin_orders.assign_courier(s, order, a, admin_id=world.admin_id),
        lambda s: admin_orders.assign_courier(s, order, b, admin_id=world.admin_id),
    )
    # Serialized on the order row: the second one reassigned (DEC-51).
    assert await _active(world, order_id=order) == 1


async def test_two_assignments_of_one_order_keep_one_active(world: World) -> None:
    for _ in range(ROUNDS):
        await _two_assignments_of_one_order_keep_one_active(world)


async def _two_auto_assignments_of_different_orders(world: World) -> None:
    # Only these couriers are available in this round.
    async with world.engine.begin() as conn:
        await conn.execute(
            update(CourierProfile)
            .where(CourierProfile.user_id.in_(world.users))
            .values(is_available=False)
        )
    couriers = [await world.courier(limit=1), await world.courier(limit=1)]
    orders = [await world.order(), await world.order(), await world.order()]
    results = await _together(
        world.engine,
        *(lambda s, o=o: admin_orders.auto_assign_courier(s, o) for o in orders),
    )
    # Two couriers with limit 1: two orders get one each, the third none.
    assert _codes(results) == ["", "", "NO_COURIER_AVAILABLE"]
    for courier in couriers:
        assert await _active(world, courier_id=courier) == 1


async def test_two_auto_assignments_of_different_orders(world: World) -> None:
    for _ in range(ROUNDS):
        await _two_auto_assignments_of_different_orders(world)


async def _assignment_against_deactivation(world: World) -> None:
    courier = await world.courier(limit=2)
    order = await world.order()
    results = await _together(
        world.engine,
        lambda s: admin_orders.assign_courier(s, order, courier, admin_id=world.admin_id),
        lambda s: staff.deactivate(s, courier),
    )
    assign_result, deactivate_result = results
    is_active = await world.scalar(select(User.is_active).where(User.id == courier))
    active = await _active(world, courier_id=courier)
    if isinstance(assign_result, AppError):
        # Deactivation first: the assignment saw is_active = false.
        assert assign_result.code == "COURIER_NOT_AVAILABLE"
        assert is_active is False and active == 0
    else:
        # Assignment first: the deactivation saw the assignment (DEC-150).
        assert isinstance(deactivate_result, AppError)
        assert deactivate_result.code == "COURIER_HAS_ACTIVE_ASSIGNMENTS"
        assert is_active is True and active == 1


async def test_assignment_against_deactivation(world: World) -> None:
    for _ in range(ROUNDS):
        await _assignment_against_deactivation(world)


async def _assignment_against_role_removal(world: World) -> None:
    courier = await world.courier(limit=2)
    order = await world.order()
    results = await _together(
        world.engine,
        lambda s: admin_orders.assign_courier(s, order, courier, admin_id=world.admin_id),
        lambda s: staff.update_roles(s, courier, StaffRolesUpdate(roles=["cook"])),
    )
    assign_result, roles_result = results
    is_courier = await world.scalar(
        select(func.count())
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == courier, Role.name == RoleName.COURIER.value)
    )
    active = await _active(world, courier_id=courier)
    if isinstance(assign_result, AppError):
        assert assign_result.code == "COURIER_NOT_AVAILABLE"
        assert is_courier == 0 and active == 0
    else:
        assert isinstance(roles_result, AppError)
        assert roles_result.code == "COURIER_HAS_ACTIVE_ASSIGNMENTS"  # DEC-29
        assert is_courier == 1 and active == 1


async def test_assignment_against_role_removal(world: World) -> None:
    for _ in range(ROUNDS):
        await _assignment_against_role_removal(world)


async def _accept_against_reassignment(world: World) -> None:
    old, new = await world.courier(limit=3), await world.courier(limit=3)
    order = await world.order()
    await world.assign_directly(order, old)
    accept_result, _ = await _together(
        world.engine,
        lambda s: courier_service.accept(s, old, order),
        lambda s: admin_orders.assign_courier(s, order, new, admin_id=world.admin_id),
    )
    rows = dict(
        await world.rows(
            select(CourierAssignment.courier_id, CourierAssignment.status).where(
                CourierAssignment.order_id == order
            )
        )
    )
    # Reassignment always applies; the old courier's accept either came
    # first (then cancelled) or found no active assignment (404).
    assert rows == {old: "cancelled", new: "active"}
    if isinstance(accept_result, AppError):
        assert accept_result.code == "NOT_FOUND"


async def test_accept_against_reassignment(world: World) -> None:
    for _ in range(ROUNDS):
        await _accept_against_reassignment(world)


async def _decline_against_reassignment(world: World) -> None:
    old, new = await world.courier(limit=3), await world.courier(limit=3)
    order = await world.order()
    await world.assign_directly(order, old)
    decline_result, _ = await _together(
        world.engine,
        lambda s: courier_service.decline(s, old, order, DeclineIn()),
        lambda s: admin_orders.assign_courier(s, order, new, admin_id=world.admin_id),
    )
    rows = dict(
        await world.rows(
            select(CourierAssignment.courier_id, CourierAssignment.status).where(
                CourierAssignment.order_id == order
            )
        )
    )
    assert rows[new] == "active" and await _active(world, order_id=order) == 1
    if isinstance(decline_result, AppError):
        assert decline_result.code == "NOT_FOUND" and rows[old] == "cancelled"
    else:
        assert rows[old] == "declined"


async def test_decline_against_reassignment(world: World) -> None:
    for _ in range(ROUNDS):
        await _decline_against_reassignment(world)


async def _picked_up_against_cancellation(world: World) -> None:
    courier = await world.courier(limit=3)
    order = await world.order("ready_for_pickup")
    await world.assign_directly(order, courier, accepted=True)
    picked, cancelled = await _together(
        world.engine,
        lambda s: courier_service.picked_up(s, courier, order),
        lambda s: admin_orders.change_order_status(
            s, order, StatusChange(status="cancelled", comment="тест"), admin_id=world.admin_id
        ),
    )
    status = await world.scalar(select(Order.status).where(Order.id == order))
    assignment = await world.scalar(
        select(CourierAssignment.status).where(CourierAssignment.order_id == order)
    )
    if isinstance(picked, AppError):
        # The cancellation won (DEC-41): the courier lost the assignment.
        assert picked.code == "NOT_FOUND"
        assert (status, assignment) == ("cancelled", "cancelled")
    else:
        # The courier won: no cancellation after departure (DEC-33).
        assert isinstance(cancelled, AppError)
        assert cancelled.code == "CANCELLATION_NOT_ALLOWED"
        assert (status, assignment) == ("out_for_delivery", "active")


async def test_picked_up_against_cancellation(world: World) -> None:
    for _ in range(ROUNDS):
        await _picked_up_against_cancellation(world)


async def _delivered_against_override_and_cancellation(world: World) -> None:
    courier = await world.courier(limit=3)
    order = await world.order("out_for_delivery")
    await world.assign_directly(order, courier, accepted=True)
    await _together(
        world.engine,
        lambda s: courier_service.delivered(s, courier, order),
        lambda s: admin_orders.change_order_status(
            s,
            order,
            StatusChange(status="completed", comment="по телефону"),
            admin_id=world.admin_id,
        ),
        lambda s: admin_orders.change_order_status(
            s, order, StatusChange(status="cancelled", comment="тест"), admin_id=world.admin_id
        ),
    )
    assert await world.scalar(select(Order.status).where(Order.id == order)) == "completed"
    payments = await world.rows(select(Payment.status).where(Payment.order_id == order))
    assert [p.status for p in payments] == ["succeeded"]
    assert (
        await world.scalar(
            select(CourierAssignment.status).where(CourierAssignment.order_id == order)
        )
        == "completed"
    )
    completions = await world.scalar(
        text(
            "SELECT count(*) FROM order_status_history "
            "WHERE order_id = :id AND new_status = 'completed'"
        ).bindparams(id=order)
    )
    assert completions == 1


async def test_delivered_against_override_and_cancellation(world: World) -> None:
    for _ in range(ROUNDS):
        await _delivered_against_override_and_cancellation(world)


async def _waits(task: asyncio.Task, seconds: float = 0.7) -> bool:
    """True if the task is still blocked (waiting for a lock) after `seconds`."""
    await asyncio.sleep(seconds)
    return not task.done()


async def test_assignment_waits_for_a_deactivation_in_progress(world: World) -> None:
    """Deterministic: the staff lock (FOR NO KEY UPDATE on users, DEC-140)
    blocks the assignment's FOR SHARE until commit (DEC-151 п. 6)."""
    courier = await world.courier(limit=2)
    order = await world.order()
    async with world.engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(
            select(User.id).where(User.id == courier).with_for_update(key_share=True)
        )
        task = asyncio.create_task(
            _run(
                world.engine,
                lambda s: admin_orders.assign_courier(s, order, courier, admin_id=world.admin_id),
            )
        )
        assert await _waits(task), "the assignment did not wait for the users lock"
        await conn.execute(update(User).where(User.id == courier).values(is_active=False))
        await tx.commit()
    result = await asyncio.wait_for(task, timeout=TIMEOUT)
    assert isinstance(result, AppError) and result.code == "COURIER_NOT_AVAILABLE"
    assert await _active(world, courier_id=courier) == 0


async def test_deactivation_waits_for_an_assignment_in_progress(world: World) -> None:
    """Deterministic: an assignment holding users FOR SHARE and the profile
    blocks the deactivation; after commit it sees the assignment (DEC-150)."""
    courier = await world.courier(limit=2)
    order = await world.order()
    async with world.engine.connect() as conn:
        tx = await conn.begin()
        # The lock order of an assignment: orders -> users (SHARE) -> profile.
        await conn.execute(select(Order.id).where(Order.id == order).with_for_update())
        await conn.execute(select(User.id).where(User.id == courier).with_for_update(read=True))
        await conn.execute(
            select(CourierProfile.user_id)
            .where(CourierProfile.user_id == courier)
            .with_for_update()
        )
        task = asyncio.create_task(_run(world.engine, lambda s: staff.deactivate(s, courier)))
        assert await _waits(task), "the deactivation did not wait for the assignment"
        await conn.execute(
            insert(CourierAssignment).values(
                order_id=order,
                courier_id=courier,
                assigned_by=world.admin_id,
                assignment_type="manual",
                assigned_at=func.now(),
            )
        )
        await tx.commit()
    result = await asyncio.wait_for(task, timeout=TIMEOUT)
    assert isinstance(result, AppError) and result.code == "COURIER_HAS_ACTIVE_ASSIGNMENTS"
    assert await world.scalar(select(User.is_active).where(User.id == courier)) is True


async def test_courier_action_does_not_wait_for_the_staff_lock(world: World) -> None:
    """Deterministic: a courier action holds the order and only key-shares
    `users` (history FK), which FOR NO KEY UPDATE does not block: no wait,
    hence no cycle with a staff operation (DEC-151 п. 6)."""
    courier = await world.courier(limit=2)
    order = await world.order("ready_for_pickup")
    await world.assign_directly(order, courier, accepted=True)
    async with world.engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(
            select(User.id).where(User.id == courier).with_for_update(key_share=True)
        )
        result = await asyncio.wait_for(
            _run(world.engine, lambda s: courier_service.picked_up(s, courier, order)), timeout=5
        )
        await tx.rollback()
    assert not isinstance(result, AppError), result
    assert await world.scalar(select(Order.status).where(Order.id == order)) == "out_for_delivery"
