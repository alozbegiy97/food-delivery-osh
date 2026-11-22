"""Stage 8 — administration and kitchen (API §9; DATABASE_SCHEMA.md §7.1, §7.6,
§9.1, §10; DEC-25, DEC-27…DEC-29, DEC-43, DEC-45, DEC-53, DEC-82, DEC-90,
DEC-97, DEC-100, DEC-101, DEC-106, DEC-107, DEC-111…DEC-114, DEC-150).

Inside the rolled-back transaction of `api_client`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.orders.models import CancellationRequest, Order, OrderStatusHistory
from app.modules.payments.models import Payment
from app.modules.users.enums import RoleName
from app.modules.users.models import CourierProfile, RefreshToken, Role, User, UserRole
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

ADMIN_URL = f"{API}/admin"


@pytest.fixture
async def admin(demo: AsyncConnection) -> dict[str, str]:
    return await make_user(demo, RoleName.ADMIN.value)


@pytest.fixture
async def cook(demo: AsyncConnection) -> dict[str, str]:
    return await make_user(demo, RoleName.COOK.value)


async def _cash_order(client: httpx.AsyncClient, conn: AsyncConnection, customer: dict) -> dict:
    await add_kompot(client, conn, customer, 3)
    return ok(
        await client.post(f"{API}/orders", json=order_body("420.00"), headers=customer | key()), 201
    )


async def _mock_order(client: httpx.AsyncClient, conn: AsyncConnection, customer: dict) -> dict:
    await add_kompot(client, conn, customer, 3)
    return ok(
        await client.post(
            f"{API}/orders",
            json=order_body("420.00", payment_method_code="mock_card"),
            headers=customer | key(),
        ),
        201,
    )


async def _set_status(
    client: httpx.AsyncClient, admin: dict, order_id: str, status: str, comment=None
):
    body = {"status": status} if comment is None else {"status": status, "comment": comment}
    return await client.patch(f"{ADMIN_URL}/orders/{order_id}/status", json=body, headers=admin)


async def _payments(conn: AsyncConnection, order_id: str) -> list[str]:
    return list(
        await conn.scalars(
            select(Payment.status).where(Payment.order_id == order_id).order_by(Payment.created_at)
        )
    )


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------


async def test_roles_are_checked_on_the_backend(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, cook: dict, customer: dict
) -> None:
    for path in (
        "/dashboard/summary",
        "/orders",
        "/cancellation-requests",
        "/staff",
        "/settings",
        "/working-hours",
        "/delivery-zones",
    ):
        error(await api_client.get(f"{ADMIN_URL}{path}"), 401, "UNAUTHORIZED")
        for headers in (cook, customer):
            error(await api_client.get(f"{ADMIN_URL}{path}", headers=headers), 403, "FORBIDDEN")
        ok(await api_client.get(f"{ADMIN_URL}{path}", headers=admin))
    error(await api_client.get(f"{API}/staff/kitchen/orders", headers=customer), 403, "FORBIDDEN")
    ok(await api_client.get(f"{API}/staff/kitchen/orders", headers=cook))
    ok(await api_client.get(f"{API}/staff/kitchen/orders", headers=admin))


# --------------------------------------------------------------------------
# Orders: queue, transitions, kitchen
# --------------------------------------------------------------------------


async def test_full_pickup_flow_admin_and_kitchen(
    api_client: httpx.AsyncClient,
    demo: AsyncConnection,
    admin: dict,
    cook: dict,
    customer: dict,
    clock: Clock,
) -> None:
    order = await _cash_order(api_client, demo, customer)
    queue = ok(await api_client.get(f"{ADMIN_URL}/orders", headers=admin))
    assert [o["order_number"] for o in queue["items"]] == [order["order_number"]]
    detail = ok(await api_client.get(f"{ADMIN_URL}/orders/{order['id']}", headers=admin))
    assert set(detail["allowed_statuses"]) == {"confirmed", "rejected", "cancelled"}
    assert detail["customer_phone"] == "+996700123456"  # the admin sees the customer

    confirmed = ok(await _set_status(api_client, admin, order["id"], "confirmed"))
    assert confirmed["status"] == "confirmed"
    assert confirmed["admin_history"][-1]["changed_by_name"] == "Покупатель"  # make_user name

    # The cook sees the order without personal or payment data (DEC-25, DEC-106).
    kitchen = ok(await api_client.get(f"{API}/staff/kitchen/orders", headers=cook))
    [ticket] = kitchen["items"]
    assert set(ticket) == {
        "id",
        "order_number",
        "delivery_type",
        "status",
        "confirmed_at",
        "preparing_started_at",
        "items",
    }
    assert set(ticket["items"][0]) == {
        "product_name",
        "variant_name",
        "quantity",
        "special_instructions",
        "modifiers",
    }
    raw = str(kitchen)
    for secret in ("+996700123456", "Айбек", "customer", "payment", "total", "address"):
        assert secret not in raw

    started = ok(
        await api_client.post(f"{API}/staff/kitchen/orders/{order['id']}/start", headers=cook)
    )
    assert started["status"] == "preparing" and started["preparing_started_at"]
    error(
        await api_client.post(f"{API}/staff/kitchen/orders/{order['id']}/start", headers=cook),
        409,
        "INVALID_STATUS_TRANSITION",
    )
    ready = ok(
        await api_client.post(f"{API}/staff/kitchen/orders/{order['id']}/ready", headers=cook)
    )
    assert ready["status"] == "ready_for_pickup"
    # The cook cannot complete or confirm through the admin API.
    error(await _set_status(api_client, cook, order["id"], "completed"), 403, "FORBIDDEN")

    done = ok(await _set_status(api_client, admin, order["id"], "completed"))
    assert done["status"] == "completed" and done["completed_at"]
    assert await _payments(demo, order["id"]) == ["succeeded"]  # DEC-43
    paid_at = await demo.scalar(select(Payment.paid_at).where(Payment.order_id == order["id"]))
    assert paid_at is not None
    assert ok(await api_client.get(f"{API}/staff/kitchen/orders", headers=cook))["items"] == []
    error(
        await _set_status(api_client, admin, order["id"], "cancelled", "поздно"),
        409,
        "CANCELLATION_NOT_ALLOWED",  # DEC-33, API §1.1
    )
    # Other forbidden transitions keep their code.
    error(
        await _set_status(api_client, admin, order["id"], "preparing"),
        409,
        "INVALID_STATUS_TRANSITION",
    )
    # One test transaction: the history rows share created_at, compare as a set.
    history = {(h["old_status"], h["new_status"]) for h in done["admin_history"]}
    assert history == {
        (None, "pending"),
        ("pending", "confirmed"),
        ("confirmed", "preparing"),
        ("preparing", "ready_for_pickup"),
        ("ready_for_pickup", "completed"),
    }


async def test_unpaid_mock_orders_stay_out_of_the_queue(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    unpaid = await _mock_order(api_client, demo, customer)
    assert ok(await api_client.get(f"{ADMIN_URL}/orders", headers=admin))["items"] == []
    awaiting = ok(
        await api_client.get(
            f"{ADMIN_URL}/orders", params={"awaiting_payment": True}, headers=admin
        )
    )
    assert [o["id"] for o in awaiting["items"]] == [unpaid["id"]]
    assert awaiting["items"][0]["awaiting_payment"] is True
    detail = ok(await api_client.get(f"{ADMIN_URL}/orders/{unpaid['id']}", headers=admin))
    assert detail["allowed_statuses"] == []
    for status, comment in (("confirmed", None), ("rejected", "нет"), ("cancelled", "нет")):
        error(
            await _set_status(api_client, admin, unpaid["id"], status, comment),
            409,
            "PAYMENT_REQUIRED",
        )

    attempt = await demo.scalar(select(Payment.id).where(Payment.order_id == unpaid["id"]))
    ok(
        await api_client.post(
            f"{API}/payments/mock/confirm",
            json={"order_id": unpaid["id"], "attempt_id": str(attempt), "outcome": "success"},
            headers=customer,
        )
    )
    queue = ok(await api_client.get(f"{ADMIN_URL}/orders", headers=admin))
    assert [o["id"] for o in queue["items"]] == [unpaid["id"]]
    ok(await _set_status(api_client, admin, unpaid["id"], "confirmed"))


async def test_reject_and_cancel(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    first = await _cash_order(api_client, demo, customer)
    ok(
        await api_client.post(
            f"{API}/orders/{first['id']}/cancellation-requests",
            json={"reason": "передумал"},
            headers=customer,
        ),
        201,
    )
    error(await _set_status(api_client, admin, first["id"], "rejected"), 422, "VALIDATION_ERROR")
    rejected = ok(await _set_status(api_client, admin, first["id"], "rejected", "Нет продуктов"))
    assert rejected["status"] == "rejected"
    assert await _payments(demo, first["id"]) == ["cancelled"]  # DEC-100
    request = (
        await demo.execute(
            select(CancellationRequest).where(CancellationRequest.order_id == first["id"])
        )
    ).one()
    assert request.status == "rejected"
    assert request.admin_comment == "Заказ отклонён рестораном. Запрос отмены закрыт автоматически"

    second = await _cash_order(api_client, demo, customer)
    ok(await _set_status(api_client, admin, second["id"], "confirmed"))
    error(
        await _set_status(api_client, admin, second["id"], "rejected", "x"),
        409,
        "INVALID_STATUS_TRANSITION",
    )
    cancelled = ok(await _set_status(api_client, admin, second["id"], "cancelled", "Закрываемся"))
    assert cancelled["cancellation_reason_code"] == "admin_decision"
    again = ok(await _set_status(api_client, admin, second["id"], "cancelled", "ещё раз"))
    assert again["status"] == "cancelled"  # idempotent (DEC-82)
    rows = await demo.scalar(
        select(func.count())
        .select_from(OrderStatusHistory)
        .where(
            OrderStatusHistory.order_id == second["id"],
            OrderStatusHistory.new_status == "cancelled",
        )
    )
    assert rows == 1
    assert await _payments(demo, second["id"]) == ["cancelled"]

    # A delivery is never completed from ready_for_pickup (pickup only, §7.1).
    await add_kompot(api_client, demo, customer, 4)
    delivery = ok(
        await api_client.post(
            f"{API}/orders", json=delivery_body("660.00"), headers=customer | key()
        ),
        201,
    )
    for status in ("confirmed", "preparing", "ready_for_pickup"):
        ok(await _set_status(api_client, admin, delivery["id"], status))
    detail = ok(await api_client.get(f"{ADMIN_URL}/orders/{delivery['id']}", headers=admin))
    assert "completed" not in detail["allowed_statuses"]
    error(
        await _set_status(api_client, admin, delivery["id"], "completed"),
        409,
        "INVALID_STATUS_TRANSITION",
    )


async def test_cancellation_requests_review(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    approve_me = await _cash_order(api_client, demo, customer)
    reject_me = await _cash_order(api_client, demo, customer)
    r1 = ok(
        await api_client.post(
            f"{API}/orders/{approve_me['id']}/cancellation-requests",
            json={"reason": "Долго"},
            headers=customer,
        ),
        201,
    )
    r2 = ok(
        await api_client.post(
            f"{API}/orders/{reject_me['id']}/cancellation-requests",
            json={"reason": "Ошибся"},
            headers=customer,
        ),
        201,
    )
    listing = ok(await api_client.get(f"{ADMIN_URL}/cancellation-requests", headers=admin))
    assert {r["id"] for r in listing["items"]} == {r1["id"], r2["id"]}

    approved = ok(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r1['id']}/approve", headers=admin
        )
    )
    assert approved["status"] == "approved" and approved["order_status"] == "cancelled"
    order = (await demo.execute(select(Order).where(Order.id == approve_me["id"]))).one()
    assert order.cancellation_reason_code == "customer_request"
    ok(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r1['id']}/approve", headers=admin
        )
    )
    error(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r1['id']}/reject",
            json={"admin_comment": "нет"},
            headers=admin,
        ),
        409,
        "CANCELLATION_NOT_ALLOWED",
    )

    error(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r2['id']}/reject",
            json={"admin_comment": "  "},
            headers=admin,
        ),
        422,
        "VALIDATION_ERROR",
    )
    rejected = ok(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r2['id']}/reject",
            json={"admin_comment": "Уже готовим"},
            headers=admin,
        )
    )
    assert rejected["status"] == "rejected" and rejected["order_status"] == "pending"
    ok(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r2['id']}/reject",
            json={"admin_comment": "другой"},
            headers=admin,
        )
    )
    error(
        await api_client.post(
            f"{ADMIN_URL}/cancellation-requests/{r2['id']}/approve", headers=admin
        ),
        409,
        "CANCELLATION_NOT_ALLOWED",
    )
    customer_view = ok(await api_client.get(f"{API}/orders/{reject_me['id']}", headers=customer))
    assert customer_view["cancellation_requests"][0]["admin_comment"] == "Уже готовим"
    assert customer_view["can_request_cancellation"] is True  # a new request is allowed (DEC-42)


# --------------------------------------------------------------------------
# Staff (DEC-150)
# --------------------------------------------------------------------------


async def test_staff_lifecycle(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict
) -> None:
    body = {
        "email": "Cook.Demo@Example.com",
        "full_name": "Повар Тест",
        "phone": "0700 11 22 33",
        "roles": ["cook"],
        "temporary_password": "temp1pass",
    }
    created = ok(await api_client.post(f"{ADMIN_URL}/staff", json=body, headers=admin), 201)
    assert created["email"] == "cook.demo@example.com"
    assert created["roles"] == ["cook"] and created["must_change_password"] is True
    error(
        await api_client.post(f"{ADMIN_URL}/staff", json=body, headers=admin),
        409,
        "EMAIL_ALREADY_EXISTS",
    )
    for bad in (
        {"roles": ["admin"]},
        {"roles": ["customer"]},
        {"roles": []},
        {"temporary_password": "short1"},
        {"temporary_password": "nodigitsatall"},
    ):
        error(
            await api_client.post(
                f"{ADMIN_URL}/staff", json={**body, "email": "x@example.com", **bad}, headers=admin
            ),
            422,
            "VALIDATION_ERROR",
        )

    # The employee signs in with the temporary password and must change it (DEC-28).
    login = await api_client.post(
        f"{API}/auth/login",
        json={"email": body["email"], "password": "temp1pass"},
        headers={"Origin": "http://test", "X-CSRF-Protection": "1"},
    )
    token = ok(login)["access_token"]
    me = ok(await api_client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}))
    assert me["must_change_password"] is True
    error(
        await api_client.get(
            f"{API}/staff/kitchen/orders", headers={"Authorization": f"Bearer {token}"}
        ),
        403,
        "PASSWORD_CHANGE_REQUIRED",
    )

    # Roles: courier creates courier_profiles (DEC-27); admin/customer are not touched.
    courier = ok(
        await api_client.patch(
            f"{ADMIN_URL}/staff/{created['id']}/roles",
            json={"roles": ["cook", "courier"]},
            headers=admin,
        )
    )
    assert courier["roles"] == ["cook", "courier"]
    assert (
        await demo.scalar(
            select(func.count())
            .select_from(CourierProfile)
            .where(CourierProfile.user_id == created["id"])
        )
        == 1
    )
    ok(
        await api_client.patch(
            f"{ADMIN_URL}/staff/{created['id']}/roles", json={"roles": ["cook"]}, headers=admin
        )
    )

    listing = ok(await api_client.get(f"{ADMIN_URL}/staff", headers=admin))
    assert [s["email"] for s in listing["items"]] == ["cook.demo@example.com"]  # no admin/customers

    # Deactivation revokes every session and closes access at once.
    tokens = await demo.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == created["id"], RefreshToken.revoked_at.is_(None))
    )
    assert tokens == 1
    off = ok(await api_client.post(f"{ADMIN_URL}/staff/{created['id']}/deactivate", headers=admin))
    assert off["is_active"] is False
    assert (
        await demo.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == created["id"], RefreshToken.revoked_at.is_(None))
        )
        == 0
    )
    error(
        await api_client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}),
        401,
        "UNAUTHORIZED",
    )
    ok(
        await api_client.post(f"{ADMIN_URL}/staff/{created['id']}/deactivate", headers=admin)
    )  # idempotent

    on = ok(await api_client.post(f"{ADMIN_URL}/staff/{created['id']}/reactivate", headers=admin))
    assert on["is_active"] is True and on["must_change_password"] is True  # password kept
    ok(await api_client.post(f"{ADMIN_URL}/staff/{created['id']}/reactivate", headers=admin))
    ok(
        await api_client.post(
            f"{API}/auth/login",
            json={"email": body["email"], "password": "temp1pass"},
            headers={"Origin": "http://test", "X-CSRF-Protection": "1"},
        )
    )


async def _staff_user(conn: AsyncConnection, *roles: str) -> str:
    role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
    user_id = await conn.scalar(
        insert(User)
        .values(email=f"{uuid.uuid4().hex}@example.com", password_hash="x", full_name="Смешанный")
        .returning(User.id)
    )
    for role in roles:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_ids[role]))
    return str(user_id)


async def test_admin_accounts_are_protected(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict
) -> None:
    both = await _staff_user(demo, RoleName.ADMIN.value, RoleName.COOK.value)
    for action in ("deactivate", "reactivate"):
        error(
            await api_client.post(f"{ADMIN_URL}/staff/{both}/{action}", headers=admin),
            409,
            "ADMIN_ACCOUNT_PROTECTED",
        )
    # An admin without staff roles is protected too, not "not found" (API §9).
    admin_only = await _staff_user(demo, RoleName.ADMIN.value)
    for action in ("deactivate", "reactivate"):
        error(
            await api_client.post(f"{ADMIN_URL}/staff/{admin_only}/{action}", headers=admin),
            409,
            "ADMIN_ACCOUNT_PROTECTED",
        )
    # Changing the staff roles keeps the admin role (DEC-150).
    kept = ok(
        await api_client.patch(
            f"{ADMIN_URL}/staff/{both}/roles", json={"roles": ["courier"]}, headers=admin
        )
    )
    assert kept["roles"] == ["admin", "courier"] and kept["is_active"] is True
    # A plain customer is not staff: not listed, not managed.
    plain = await _staff_user(demo, RoleName.CUSTOMER.value)
    assert plain not in {
        i["id"] for i in ok(await api_client.get(f"{ADMIN_URL}/staff", headers=admin))["items"]
    }
    error(
        await api_client.post(f"{ADMIN_URL}/staff/{plain}/deactivate", headers=admin),
        404,
        "NOT_FOUND",
    )
    error(
        await api_client.patch(
            f"{ADMIN_URL}/staff/{plain}/roles", json={"roles": ["cook"]}, headers=admin
        ),
        404,
        "NOT_FOUND",
    )


# --------------------------------------------------------------------------
# Settings and working hours (DEC-107, DEC-150)
# --------------------------------------------------------------------------


async def test_settings_and_working_hours(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict
) -> None:
    settings = ok(await api_client.get(f"{ADMIN_URL}/settings", headers=admin))
    assert settings["timezone"] == "Asia/Bishkek"
    changed = ok(
        await api_client.patch(
            f"{ADMIN_URL}/settings",
            json={
                "latitude": "40.5300000",
                "longitude": "72.8000000",
                "min_order_amount": "350.50",
                "phone": "0700 12 34 56",
                "pickup_enabled": False,
            },
            headers=admin,
        )
    )
    assert (
        changed["latitude"],
        changed["min_order_amount"],
        changed["phone"],
        changed["pickup_enabled"],
    ) == ("40.5300000", "350.50", "+996700123456", False)
    for bad in (
        {"timezone": "UTC"},
        {"latitude": "40.5"},
        {},
        {"restaurant_name": None},
        {"min_order_amount": "-1"},
        {"min_order_amount": "10.001"},
        {"phone": "123"},
    ):
        error(
            await api_client.patch(f"{ADMIN_URL}/settings", json=bad, headers=admin),
            422,
            "VALIDATION_ERROR",
        )

    week = [
        {"weekday": d, "is_closed": False, "opens_at": "10:00", "closes_at": "23:00"}
        for d in range(7)
    ]
    week[4] = {
        "weekday": 4,
        "is_closed": False,
        "opens_at": "18:00",
        "closes_at": "02:00",
    }  # Fri night
    week[6] = {"weekday": 6, "is_closed": True}
    saved = ok(
        await api_client.put(f"{ADMIN_URL}/working-hours", json={"items": week}, headers=admin)
    )
    assert saved["items"][4]["closes_at"] == "02:00:00" and saved["items"][6]["is_closed"] is True
    public = ok(await api_client.get(f"{API}/restaurant"))
    assert public["working_hours"][4]["closes_at"] == "02:00"

    overlap = [dict(day) for day in week]
    overlap[5] = {"weekday": 5, "is_closed": False, "opens_at": "01:00", "closes_at": "23:00"}
    body = error(
        await api_client.put(f"{ADMIN_URL}/working-hours", json={"items": overlap}, headers=admin),
        422,
        "INVALID_WORKING_HOURS",
    )
    assert body["details"][0]["problem"] == "overnight_overlaps_next_day"
    same = [dict(day) for day in week]
    same[0] = {"weekday": 0, "is_closed": False, "opens_at": "10:00", "closes_at": "10:00"}
    error(
        await api_client.put(f"{ADMIN_URL}/working-hours", json={"items": same}, headers=admin),
        422,
        "INVALID_WORKING_HOURS",
    )
    twice = [dict(day) for day in week]
    twice[1] = dict(week[0])
    error(
        await api_client.put(f"{ADMIN_URL}/working-hours", json={"items": twice}, headers=admin),
        422,
        "INVALID_WORKING_HOURS",
    )
    error(
        await api_client.put(f"{ADMIN_URL}/working-hours", json={"items": week[:6]}, headers=admin),
        422,
        "VALIDATION_ERROR",
    )


# --------------------------------------------------------------------------
# Delivery zones (DEC-53, DEC-102, DEC-150)
# --------------------------------------------------------------------------


def _square(x1: float, y1: float, x2: float, y2: float) -> list:
    return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]]


async def test_delivery_zones(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict
) -> None:
    url = f"{ADMIN_URL}/delivery-zones"
    [demo_zone] = ok(await api_client.get(url, headers=admin))["items"]
    assert demo_zone["boundary"]["type"] == "MultiPolygon"

    base = {"name": "Восток", "delivery_fee": "150.00", "min_order_amount": "0"}
    # Touching the demo zone along lon 72.86 is allowed; a Polygon is stored as MultiPolygon.
    east = ok(
        await api_client.post(
            url,
            json={
                **base,
                "boundary": {"type": "Polygon", "coordinates": _square(72.86, 40.49, 72.95, 40.57)},
            },
            headers=admin,
        ),
        201,
    )
    assert east["boundary"]["type"] == "MultiPolygon"

    body = error(
        await api_client.post(
            url,
            json={
                **base,
                "name": "Внутри",
                "boundary": {"type": "Polygon", "coordinates": _square(72.80, 40.50, 72.90, 40.55)},
            },
            headers=admin,
        ),
        422,
        "ZONE_OVERLAP",
    )
    assert {d["message"] for d in body["details"]} == {demo_zone["name"], "Восток"}
    bowtie = [[[72.0, 40.0], [72.1, 40.1], [72.1, 40.0], [72.0, 40.1], [72.0, 40.0]]]
    error(
        await api_client.post(
            url,
            json={**base, "boundary": {"type": "Polygon", "coordinates": bowtie}},
            headers=admin,
        ),
        422,
        "INVALID_GEOMETRY",
    )
    error(
        await api_client.post(
            url,
            json={
                **base,
                "boundary": {"type": "Polygon", "coordinates": _square(200, 40, 201, 41)},
            },
            headers=admin,
        ),
        422,
        "INVALID_GEOMETRY",
    )
    error(
        await api_client.post(
            url,
            json={**base, "boundary": {"type": "Point", "coordinates": [72, 40]}},
            headers=admin,
        ),
        422,
        "VALIDATION_ERROR",
    )
    other_srid = {
        "type": "Polygon",
        "coordinates": _square(1, 1, 2, 2),
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
    }
    error(
        await api_client.post(url, json={**base, "boundary": other_srid}, headers=admin),
        422,
        "INVALID_GEOMETRY",
    )

    # An inactive overlapping zone may exist; activating it is checked.
    inner = ok(
        await api_client.post(
            url,
            json={
                **base,
                "name": "Черновик",
                "is_active": False,
                "boundary": {"type": "Polygon", "coordinates": _square(72.80, 40.50, 72.90, 40.55)},
            },
            headers=admin,
        ),
        201,
    )
    error(
        await api_client.patch(f"{url}/{inner['id']}", json={"is_active": True}, headers=admin),
        422,
        "ZONE_OVERLAP",
    )

    # The point on the shared border picks the cheaper zone (DEC-102): demo 100 < 150.
    changed = ok(
        await api_client.patch(f"{url}/{east['id']}", json={"delivery_fee": "80"}, headers=admin)
    )
    assert changed["delivery_fee"] == "80.00"  # normalised to 2 decimals in the response
    error(
        await api_client.patch(
            f"{url}/{east['id']}", json={"delivery_fee": "80.001"}, headers=admin
        ),
        422,
        "VALIDATION_ERROR",
    )

    removed = ok(await api_client.delete(f"{url}/{east['id']}", headers=admin))
    assert removed["is_active"] is False  # deactivated, not deleted
    assert len(ok(await api_client.get(url, headers=admin))["items"]) == 3


# --------------------------------------------------------------------------
# Dashboard (DEC-90, DEC-111, DEC-114)
# --------------------------------------------------------------------------


async def test_dashboard_metrics(
    api_client: httpx.AsyncClient, demo: AsyncConnection, admin: dict, customer: dict, clock: Clock
) -> None:
    empty = ok(await api_client.get(f"{ADMIN_URL}/dashboard/summary", headers=admin))
    assert (
        empty["orders_count"],
        empty["revenue"],
        empty["average_check"],
        empty["active_orders"],
    ) == (0, "0.00", "0.00", 0)
    assert (
        len(
            ok(await api_client.get(f"{ADMIN_URL}/dashboard/orders-chart", headers=admin))["points"]
        )
        == 7
    )

    completed = await _cash_order(api_client, demo, customer)
    for status in ("confirmed", "preparing", "ready_for_pickup", "completed"):
        ok(await _set_status(api_client, admin, completed["id"], status))
    active = await _cash_order(api_client, demo, customer)
    ok(await _set_status(api_client, admin, active["id"], "confirmed"))
    rejected = await _cash_order(api_client, demo, customer)
    ok(await _set_status(api_client, admin, rejected["id"], "rejected", "нет"))
    timed_out = await _mock_order(api_client, demo, customer)
    unpaid = await _mock_order(api_client, demo, customer)
    await demo.execute(
        update(Order)
        .where(Order.id == timed_out["id"])
        .values(
            status="cancelled", cancellation_reason_code="payment_timeout", cancelled_at=func.now()
        )
    )
    assert unpaid

    # Days are counted in Asia/Bishkek: move the completed order to 23:30 local yesterday.
    today_local = datetime.now(UTC).astimezone(ZoneInfo("Asia/Bishkek")).date()
    yesterday = today_local - timedelta(days=1)
    late = datetime(yesterday.year, yesterday.month, yesterday.day, 17, 30, tzinfo=UTC)  # 23:30 +06
    await demo.execute(update(Order).where(Order.id == completed["id"]).values(completed_at=late))

    summary = ok(await api_client.get(f"{ADMIN_URL}/dashboard/summary", headers=admin))
    # 5 orders created; the payment_timeout one is excluded; unpaid and rejected count.
    assert summary["orders_count"] == 4
    assert summary["revenue"] == "420.00" and summary["average_check"] == "420.00"
    assert summary["active_orders"] == 1
    only_today = ok(
        await api_client.get(
            f"{ADMIN_URL}/dashboard/summary",
            params={"date_from": str(today_local), "date_to": str(today_local)},
            headers=admin,
        )
    )
    assert only_today["revenue"] == "0.00" and only_today["average_check"] == "0.00"
    assert only_today["active_orders"] == 1  # independent of the period

    chart = ok(await api_client.get(f"{ADMIN_URL}/dashboard/orders-chart", headers=admin))
    by_day = {p["date"]: p for p in chart["points"]}
    assert by_day[str(yesterday)]["revenue"] == "420.00"
    assert by_day[str(today_local)]["orders_created"] == 4

    top = ok(await api_client.get(f"{ADMIN_URL}/dashboard/top-products", headers=admin))
    assert top["items"] == [
        {"product_id": top["items"][0]["product_id"], "product_name": "Компот", "quantity": 3}
    ]
    error(
        await api_client.get(
            f"{ADMIN_URL}/dashboard/summary",
            params={"date_from": "2026-11-10", "date_to": "2026-11-01"},
            headers=admin,
        ),
        422,
        "VALIDATION_ERROR",
    )
