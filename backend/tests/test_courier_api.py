"""Stage 9 — couriers and assignments (API §9 "Couriers", §10; DATABASE_SCHEMA.md
§3.4, §7.1, §9.2, §9.3; DEC-29, DEC-33, DEC-36, DEC-41, DEC-43, DEC-48…DEC-52,
DEC-83, DEC-91, DEC-92, DEC-106, DEC-150, DEC-151).

Inside the rolled-back transaction of `api_client`; concurrency is covered
by `test_courier_concurrency.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import create_access_token, hash_password
from app.modules.delivery.models import CourierAssignment, Delivery
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.payments.models import Payment
from app.modules.users.enums import RoleName
from app.modules.users.models import CourierProfile, Role, User, UserRole
from tests.orders_support import (
    API,
    Clock,
    add_kompot,
    delivery_body,
    error,
    key,
    make_user,
    ok,
    order_body,
)

pytestmark = pytest.mark.db

ADMIN = f"{API}/admin"
COURIER = f"{API}/courier"


class Courier:
    def __init__(self, user_id: uuid.UUID, headers: dict[str, str]) -> None:
        self.id = user_id
        self.headers = headers


async def make_courier(
    conn: AsyncConnection,
    *,
    available: bool = True,
    limit: int = 1,
    name: str = "Курьер",
    profile: bool = True,
) -> Courier:
    role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=f"courier-{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("correct1horse"),
            full_name=name,
            phone="+996700000111",
        )
        .returning(User.id)
    )
    await conn.execute(
        insert(UserRole).values(user_id=user_id, role_id=role_ids[RoleName.COURIER.value])
    )
    if profile:
        await conn.execute(
            insert(CourierProfile).values(
                user_id=user_id, is_available=available, max_active_orders=limit
            )
        )
    return Courier(user_id, {"Authorization": f"Bearer {create_access_token(user_id).token}"})


@pytest.fixture
async def admin(demo: AsyncConnection) -> dict[str, str]:
    return await make_user(demo, RoleName.ADMIN.value)


async def _delivery(
    client: httpx.AsyncClient, conn: AsyncConnection, customer: dict, admin: dict, *, to: str
) -> dict:
    """A cash delivery order (660.00) moved by the administrator to `to`
    (`pending` = not moved)."""
    await add_kompot(client, conn, customer, 4)
    order = ok(
        await client.post(
            f"{API}/orders",
            json=delivery_body("660.00", comment="Позвоните у ворот"),
            headers=customer | key(),
        ),
        201,
    )
    statuses = ("confirmed", "preparing", "ready_for_pickup")
    for status in statuses[: statuses.index(to) + 1] if to != "pending" else ():
        ok(
            await client.patch(
                f"{ADMIN}/orders/{order['id']}/status", json={"status": status}, headers=admin
            )
        )
    return order


def _assign(client: httpx.AsyncClient, admin: dict, order_id: str, courier: Courier):  # noqa: ANN202
    return client.post(
        f"{ADMIN}/orders/{order_id}/assign-courier",
        json={"courier_id": str(courier.id)},
        headers=admin,
    )


def _act(client: httpx.AsyncClient, courier: Courier, order_id: str, action: str, **kw):  # noqa: ANN202
    return client.post(f"{COURIER}/orders/{order_id}/{action}", headers=courier.headers, **kw)


async def test_full_delivery_with_cash(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    courier = await make_courier(demo, name="Бакыт")
    order = await _delivery(api_client, demo, customer, admin, to="confirmed")

    detail = ok(await _assign(api_client, admin, order["id"], courier))
    [assignment] = detail["assignments"]
    assert assignment["status"] == "active" and assignment["assignment_type"] == "manual"
    assert assignment["courier_name"] == "Бакыт" and assignment["assigned_by_name"]
    assert detail["needs_courier"] is False

    me = ok(await api_client.get(f"{COURIER}/me", headers=courier.headers))
    assert me["active_assignments"] == 1 and me["max_active_orders"] == 1
    active = ok(await api_client.get(f"{COURIER}/orders", headers=courier.headers))
    assert active["kind"] == "active"
    [view] = active["items"]
    # DEC-106: what the courier needs for the delivery, nothing else.
    assert view["address"]["address_text"] == "ул. Ленина, 1"
    assert view["customer_name"] == "Айбек" and view["customer_phone"] == "+996700123456"
    assert view["customer_comment"] == "Позвоните у ворот"
    assert view["amount_to_collect"] == "660.00" and view["payment_method_code"] == "cash"
    assert view["items"][0]["product_name"]
    for hidden in ("customer_email", "payments", "status_history", "admin_history"):
        assert hidden not in view
    assert (view["can_accept"], view["can_decline"], view["can_pick_up"]) == (True, True, False)

    # Not ready yet / not accepted: picked-up refused (DEC-83).
    error(
        await _act(api_client, courier, order["id"], "picked-up"), 409, "INVALID_STATUS_TRANSITION"
    )
    accepted = ok(await _act(api_client, courier, order["id"], "accept"))
    assert accepted["accepted_at"] and accepted["status"] == "confirmed"
    again = ok(await _act(api_client, courier, order["id"], "accept"))  # DEC-151 п. 4
    assert again["accepted_at"] == accepted["accepted_at"]
    error(
        await _act(api_client, courier, order["id"], "decline"), 409, "ASSIGNMENT_ALREADY_ACCEPTED"
    )

    for status in ("preparing", "ready_for_pickup"):
        ok(
            await api_client.patch(
                f"{ADMIN}/orders/{order['id']}/status", json={"status": status}, headers=admin
            )
        )
    on_way = ok(await _act(api_client, courier, order["id"], "picked-up"))
    assert on_way["status"] == "out_for_delivery" and on_way["can_deliver"] is True
    error(
        await _act(api_client, courier, order["id"], "picked-up"), 409, "INVALID_STATUS_TRANSITION"
    )
    # DEC-33: no cancellation once the courier has the order.
    error(
        await api_client.patch(
            f"{ADMIN}/orders/{order['id']}/status",
            json={"status": "cancelled", "comment": "поздно"},
            headers=admin,
        ),
        409,
        "CANCELLATION_NOT_ALLOWED",
    )

    done = ok(await _act(api_client, courier, order["id"], "delivered"))
    assert done["assignment_status"] == "completed" and done["finished_at"]
    assert "address" not in done and "customer_phone" not in done
    repeat = ok(await _act(api_client, courier, order["id"], "delivered"))  # DEC-151 п. 4
    assert repeat == done

    status, completed_at = (
        await demo.execute(select(Order.status, Order.completed_at).where(Order.id == order["id"]))
    ).one()
    assert status == "completed" and completed_at is not None
    delivered_at = await demo.scalar(
        select(Delivery.delivered_at).where(Delivery.order_id == order["id"])
    )
    assert delivered_at is not None
    payments = (
        await demo.execute(
            select(Payment.status, Payment.paid_at).where(Payment.order_id == order["id"])
        )
    ).all()
    assert [(status, paid is not None) for status, paid in payments] == [("succeeded", True)]
    history = list(
        await demo.execute(
            select(OrderStatusHistory.new_status, OrderStatusHistory.changed_by).where(
                OrderStatusHistory.order_id == order["id"],
                OrderStatusHistory.new_status.in_(("out_for_delivery", "completed")),
            )
        )
    )
    assert sorted(history) == sorted([("out_for_delivery", courier.id), ("completed", courier.id)])
    # The repeat did not add a second completion.
    assert len(history) == 2

    # Lost access to the details; history without address or contacts (DEC-106).
    error(
        await api_client.get(f"{COURIER}/orders/{order['id']}", headers=courier.headers),
        404,
        "NOT_FOUND",
    )
    past = ok(await api_client.get(f"{COURIER}/orders?history=true", headers=courier.headers))
    assert past["kind"] == "history" and past["pagination"]["total"] == 1
    assert set(past["items"][0]) == {
        "assignment_id",
        "order_id",
        "order_number",
        "assignment_status",
        "finished_at",
        "total_amount",
        "currency",
        "payment_method_code",
    }
    admin_view = ok(await api_client.get(f"{ADMIN}/orders/{order['id']}", headers=admin))
    assert admin_view["delivered_at"] and admin_view["assignments"][0]["status"] == "completed"
    # Customers never see the courier (DEC-151 п. 7).
    mine = ok(await api_client.get(f"{API}/orders/{order['id']}", headers=customer))
    assert "Бакыт" not in str(mine) and "assignments" not in mine


async def test_assignment_rules(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    first = await make_courier(demo, name="Первый")
    second = await make_courier(demo, name="Второй")
    away = await make_courier(demo, available=False)
    no_profile = await make_courier(demo, profile=False)
    cook_headers = await make_user(demo, RoleName.COOK.value)
    order = await _delivery(api_client, demo, customer, admin, to="preparing")

    # DEC-48: delivery only, confirmed…ready_for_pickup.
    pending = await _delivery(api_client, demo, customer, admin, to="pending")
    error(await _assign(api_client, admin, pending["id"], first), 409, "INVALID_STATUS_TRANSITION")
    await add_kompot(api_client, demo, customer, 3)
    pickup = ok(
        await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=customer | key()),
        201,
    )
    ok(
        await api_client.patch(
            f"{ADMIN}/orders/{pickup['id']}/status", json={"status": "confirmed"}, headers=admin
        )
    )
    error(await _assign(api_client, admin, pickup["id"], first), 409, "INVALID_STATUS_TRANSITION")

    for unavailable in (away, no_profile):
        error(
            await _assign(api_client, admin, order["id"], unavailable), 409, "COURIER_NOT_AVAILABLE"
        )
    error(
        await api_client.post(
            f"{ADMIN}/orders/{order['id']}/assign-courier",
            json={"courier_id": str(uuid.uuid4())},
            headers=admin,
        ),
        409,
        "COURIER_NOT_AVAILABLE",
    )

    ok(await _assign(api_client, admin, order["id"], first))
    same = ok(await _assign(api_client, admin, order["id"], first))  # DEC-151 п. 4
    assert len(same["assignments"]) == 1
    # Auto-assign keeps the current assignment (DEC-151 п. 4, Q-19).
    kept = ok(
        await api_client.post(f"{ADMIN}/orders/{order['id']}/auto-assign-courier", headers=admin)
    )
    assert [a["courier_id"] for a in kept["assignments"]] == [str(first.id)]

    # The limit (1) of the first courier is reached.
    other = await _delivery(api_client, demo, customer, admin, to="confirmed")
    error(await _assign(api_client, admin, other["id"], first), 409, "COURIER_NOT_AVAILABLE")

    # Reassignment (DEC-51): old -> cancelled, the first courier loses access.
    moved = ok(await _assign(api_client, admin, order["id"], second))
    by_courier = {a["courier_id"]: a["status"] for a in moved["assignments"]}
    assert by_courier == {str(first.id): "cancelled", str(second.id): "active"}
    error(
        await api_client.get(f"{COURIER}/orders/{order['id']}", headers=first.headers),
        404,
        "NOT_FOUND",
    )
    error(await _act(api_client, first, order["id"], "accept"), 404, "NOT_FOUND")
    ok(await api_client.get(f"{COURIER}/orders/{order['id']}", headers=second.headers))

    # Somebody else's order, admin and kitchen APIs: closed for a courier.
    error(await _act(api_client, second, other["id"], "accept"), 404, "NOT_FOUND")
    for path in (f"{ADMIN}/orders", f"{ADMIN}/couriers", f"{API}/staff/kitchen/orders"):
        error(await api_client.get(path, headers=second.headers), 403, "FORBIDDEN")
    for headers in (customer, cook_headers):
        error(await api_client.get(f"{COURIER}/orders", headers=headers), 403, "FORBIDDEN")
        error(
            await api_client.post(
                f"{ADMIN}/orders/{order['id']}/assign-courier",
                json={"courier_id": str(second.id)},
                headers=headers,
            ),
            403,
            "FORBIDDEN",
        )
    error(await api_client.get(f"{COURIER}/me", headers=no_profile.headers), 403, "FORBIDDEN")

    # Cancellation releases the courier (DEC-41).
    ok(
        await api_client.patch(
            f"{ADMIN}/orders/{order['id']}/status",
            json={"status": "cancelled", "comment": "клиент передумал"},
            headers=admin,
        )
    )
    statuses = list(
        await demo.scalars(
            select(CourierAssignment.status)
            .where(CourierAssignment.order_id == order["id"])
            .order_by(CourierAssignment.assigned_at, CourierAssignment.id)
        )
    )
    assert statuses == ["cancelled", "cancelled"]
    error(
        await api_client.get(f"{COURIER}/orders/{order['id']}", headers=second.headers),
        404,
        "NOT_FOUND",
    )


async def test_decline(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    courier = await make_courier(demo)
    order = await _delivery(api_client, demo, customer, admin, to="confirmed")
    ok(await _assign(api_client, admin, order["id"], courier))
    error(
        await _act(api_client, courier, order["id"], "decline", json={"reason": "x" * 501}),
        422,
        "VALIDATION_ERROR",
    )
    done = ok(
        await _act(
            api_client, courier, order["id"], "decline", json={"reason": "  Сломался мопед "}
        )
    )
    assert done["assignment_status"] == "declined" and "address" not in done
    reason_of = select(CourierAssignment.decline_reason, CourierAssignment.declined_at).where(
        CourierAssignment.order_id == order["id"]
    )
    reason, declined_at = (await demo.execute(reason_of)).one()
    assert reason == "Сломался мопед" and declined_at is not None
    assert await demo.scalar(select(Order.status).where(Order.id == order["id"])) == "confirmed"
    # Repeat: 200, nothing rewritten (DEC-151 п. 4, Q-19).
    again = ok(await _act(api_client, courier, order["id"], "decline", json={"reason": "другое"}))
    assert again == done
    assert (await demo.execute(reason_of)).one() == (reason, declined_at)

    detail = ok(await api_client.get(f"{ADMIN}/orders/{order['id']}", headers=admin))
    assert detail["needs_courier"] is True
    assert detail["assignments"][0]["decline_reason"] == "Сломался мопед"
    listed = ok(await api_client.get(f"{ADMIN}/orders?status=confirmed", headers=admin))
    assert any(o["id"] == order["id"] and o["needs_courier"] for o in listed["items"])
    # The declined courier is excluded from auto-assignment (DEC-92).
    error(
        await api_client.post(f"{ADMIN}/orders/{order['id']}/auto-assign-courier", headers=admin),
        409,
        "NO_COURIER_AVAILABLE",
    )
    # …but the administrator may assign him manually.
    again_assigned = ok(await _assign(api_client, admin, order["id"], courier))
    assert sorted(a["status"] for a in again_assigned["assignments"]) == ["active", "declined"]
    # The courier now has an active assignment again: decline works again.
    ok(await _act(api_client, courier, order["id"], "decline"))


async def test_admin_override(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    courier = await make_courier(demo)
    order = await _delivery(api_client, demo, customer, admin, to="ready_for_pickup")
    url = f"{ADMIN}/orders/{order['id']}/status"
    # No active assignment: the override is impossible (DEC-91).
    detail = ok(await api_client.get(f"{ADMIN}/orders/{order['id']}", headers=admin))
    assert "out_for_delivery" not in detail["allowed_statuses"]
    error(
        await api_client.patch(
            url, json={"status": "out_for_delivery", "comment": "x"}, headers=admin
        ),
        409,
        "INVALID_STATUS_TRANSITION",
    )
    detail = ok(await _assign(api_client, admin, order["id"], courier))
    assert "out_for_delivery" in detail["allowed_statuses"]
    error(
        await api_client.patch(url, json={"status": "out_for_delivery"}, headers=admin),
        422,
        "VALIDATION_ERROR",
    )
    moved = ok(
        await api_client.patch(
            url,
            json={"status": "out_for_delivery", "comment": "курьер без телефона"},
            headers=admin,
        )
    )
    assert moved["status"] == "out_for_delivery"
    assert [h["new_status"] for h in moved["admin_history"] if h["is_admin_override"]] == [
        "out_for_delivery"
    ]
    # No fictitious acceptance (DEC-91).
    assert moved["assignments"][0]["accepted_at"] is None
    # Decline is forbidden after out_for_delivery even without acceptance (DEC-151 п. 5).
    error(await _act(api_client, courier, order["id"], "decline"), 409, "INVALID_STATUS_TRANSITION")
    error(await _act(api_client, courier, order["id"], "accept"), 409, "INVALID_STATUS_TRANSITION")
    # Re-assignment after departure is impossible (DEC-48, DEC-151 п. 1).
    other = await make_courier(demo)
    error(await _assign(api_client, admin, order["id"], other), 409, "INVALID_STATUS_TRANSITION")

    finished = ok(
        await api_client.patch(
            url,
            json={"status": "completed", "comment": "курьер отчитался по телефону"},
            headers=admin,
        )
    )
    assert finished["status"] == "completed" and finished["delivered_at"]
    assert finished["assignments"][0]["status"] == "completed"
    assert finished["payment_status"] == "succeeded"
    overrides = [h for h in finished["admin_history"] if h["is_admin_override"]]
    # One transaction in tests: equal timestamps, so compare as a set.
    assert sorted(h["new_status"] for h in overrides) == ["completed", "out_for_delivery"]


async def test_auto_assignment_order(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    """DEC-151 п. 3: fewest active, then the earliest last assignment
    (never assigned first), then the smallest user_id."""
    a = await make_courier(demo, limit=3)
    b = await make_courier(demo, limit=3)
    ids = sorted([a, b], key=lambda c: c.id)
    low, high = ids
    orders = [await _delivery(api_client, demo, customer, admin, to="confirmed") for _ in range(4)]

    def auto(order: dict):  # noqa: ANN202
        return api_client.post(f"{ADMIN}/orders/{order['id']}/auto-assign-courier", headers=admin)

    async def chosen(order: dict) -> uuid.UUID:
        detail = ok(await auto(order))
        [active] = [x for x in detail["assignments"] if x["status"] == "active"]
        assert active["assignment_type"] == "automatic" and active["assigned_by_name"] is None
        return uuid.UUID(active["courier_id"])

    # Only these two couriers may take orders in this test.
    await demo.execute(
        update(CourierProfile)
        .where(CourierProfile.user_id.not_in([a.id, b.id]))
        .values(is_available=False)
    )
    # Both never assigned and idle: the smaller user_id.
    assert await chosen(orders[0]) == low.id
    # Fewer active assignments wins.
    assert await chosen(orders[1]) == high.id
    # Equal load (1 and 1): the earliest last assignment wins, even against
    # the user_id order (inside one test transaction now() is constant, so
    # the times are set explicitly).
    base = datetime.now(UTC)
    for courier, age in ((high, 2), (low, 1)):
        await demo.execute(
            update(CourierAssignment)
            .where(CourierAssignment.courier_id == courier.id)
            .values(assigned_at=base - timedelta(hours=age))
        )
    assert await chosen(orders[2]) == high.id
    # high has 2 active, low 1.
    assert await chosen(orders[3]) == low.id

    # Ties on load and time: the smaller user_id.
    now = datetime.now(UTC) - timedelta(hours=1)
    await demo.execute(
        update(CourierAssignment)
        .where(CourierAssignment.courier_id.in_([a.id, b.id]))
        .values(status="cancelled", assigned_at=now)
    )
    fifth = await _delivery(api_client, demo, customer, admin, to="confirmed")
    assert await chosen(fifth) == low.id

    # Nobody available: 409, nothing written.
    await demo.execute(update(CourierProfile).values(is_available=False))
    sixth = await _delivery(api_client, demo, customer, admin, to="confirmed")
    error(await auto(sixth), 409, "NO_COURIER_AVAILABLE")
    assert (
        await demo.scalar(
            select(CourierAssignment.id).where(CourierAssignment.order_id == sixth["id"])
        )
        is None
    )


async def test_courier_settings_and_staff_rules(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    courier = await make_courier(demo, limit=2)
    url = f"{ADMIN}/couriers/{courier.id}/availability"
    for bad in ({}, {"max_active_orders": 0}, {"max_active_orders": 11}, {"is_available": None}):
        error(await api_client.patch(url, json=bad, headers=admin), 422, "VALIDATION_ERROR")
    changed = ok(await api_client.patch(url, json={"max_active_orders": 10}, headers=admin))
    assert changed["max_active_orders"] == 10 and changed["is_available"] is True
    listed = ok(await api_client.get(f"{ADMIN}/couriers", headers=admin))
    assert any(c["user_id"] == str(courier.id) for c in listed["items"])
    error(
        await api_client.patch(
            f"{ADMIN}/couriers/{uuid.uuid4()}/availability",
            json={"is_available": True},
            headers=admin,
        ),
        404,
        "NOT_FOUND",
    )

    # The courier switches only his availability.
    me = ok(
        await api_client.patch(
            f"{COURIER}/me/availability", json={"is_available": False}, headers=courier.headers
        )
    )
    assert me["is_available"] is False
    error(
        await api_client.patch(
            f"{COURIER}/me/availability",
            json={"is_available": True, "max_active_orders": 5},
            headers=courier.headers,
        ),
        422,
        "VALIDATION_ERROR",
    )
    ok(await api_client.patch(url, json={"is_available": True}, headers=admin))

    # Lowering the limit below the active count keeps the assignments.
    first = await _delivery(api_client, demo, customer, admin, to="confirmed")
    second = await _delivery(api_client, demo, customer, admin, to="confirmed")
    ok(await _assign(api_client, admin, first["id"], courier))
    ok(await _assign(api_client, admin, second["id"], courier))
    lowered = ok(await api_client.patch(url, json={"max_active_orders": 1}, headers=admin))
    assert lowered["active_assignments"] == 2
    third = await _delivery(api_client, demo, customer, admin, to="confirmed")
    error(await _assign(api_client, admin, third["id"], courier), 409, "COURIER_NOT_AVAILABLE")

    # DEC-29, DEC-150: no role removal, no deactivation with active assignments.
    error(
        await api_client.patch(
            f"{ADMIN}/staff/{courier.id}/roles", json={"roles": ["cook"]}, headers=admin
        ),
        409,
        "COURIER_HAS_ACTIVE_ASSIGNMENTS",
    )
    error(
        await api_client.post(f"{ADMIN}/staff/{courier.id}/deactivate", headers=admin),
        409,
        "COURIER_HAS_ACTIVE_ASSIGNMENTS",
    )
    assert await demo.scalar(select(User.is_active).where(User.id == courier.id)) is True
    # Without active assignments both work again.
    for order in (first, second):
        ok(
            await api_client.patch(
                f"{ADMIN}/orders/{order['id']}/status",
                json={"status": "cancelled", "comment": "тест"},
                headers=admin,
            )
        )
    off = ok(await api_client.post(f"{ADMIN}/staff/{courier.id}/deactivate", headers=admin))
    assert off["is_active"] is False
    ok(await api_client.post(f"{ADMIN}/staff/{courier.id}/reactivate", headers=admin))
    # A deactivated courier cannot be assigned.
    ok(await api_client.post(f"{ADMIN}/staff/{courier.id}/deactivate", headers=admin))
    error(await _assign(api_client, admin, third["id"], courier), 409, "COURIER_NOT_AVAILABLE")
