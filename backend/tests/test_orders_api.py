"""`POST /orders`, `GET /orders`, `GET /orders/{id}`, cancellation requests
(stage 6; API §6.2–§6.3; DATABASE_SCHEMA.md §14.1, §14.2; DEC-09/10/15/16/38/42/43/
59/61/78/97/109/148)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.cart.models import CartItem
from app.modules.catalog.models import ProductTranslation, ProductVariant
from app.modules.delivery.models import Delivery, DeliveryZone
from app.modules.orders.models import (
    CancellationRequest,
    IdempotencyKey,
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
)
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.users.enums import RoleName
from app.modules.users.models import Address
from tests.orders_support import (
    API,
    CLOSED_AT,
    INSIDE,
    OUTSIDE,
    Clock,
    add_kompot,
    delivery_body,
    error,
    key,
    make_user,
    ok,
    order_body,
    variant_of,
)

pytestmark = pytest.mark.db


async def _count(conn: AsyncConnection, model: type) -> int:
    return int(await conn.scalar(select(func.count()).select_from(model)) or 0)


async def _pizza_with_extras(
    client: httpx.AsyncClient, conn: AsyncConnection, headers: dict
) -> None:
    """Margherita 40 cm, first dough option, cheese × 2 (per-size price)."""
    detail = ok(
        await client.get(
            f"{API}/catalog/products/{(await variant_of(conn, 'demo-pizza-margherita'))[0]}"
        )
    )
    big = max(detail["variants"], key=lambda v: Decimal(v["price"]))
    dough = next(g for g in detail["modifier_groups"] if g["is_required"])
    extras = next(g for g in detail["modifier_groups"] if g["selection_type"] == "multiple")
    cheese = next(m for m in extras["modifiers"] if m["max_quantity"] > 1)
    ok(
        await client.post(
            f"{API}/cart/items",
            json={
                "product_id": detail["id"],
                "variant_id": big["id"],
                "quantity": 2,
                "modifiers": [
                    {"id": dough["modifiers"][0]["id"]},
                    {"id": cheese["id"], "quantity": 2},
                ],
                "special_instructions": "Без лука",
            },
            headers=headers,
        )
    )


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------


async def test_delivery_order_is_created_with_snapshots(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await _pizza_with_extras(api_client, demo, customer)
    quote = ok(
        await api_client.post(
            f"{API}/checkout/quote",
            json={"delivery_type": "delivery", "address": INSIDE},
            headers=customer,
        )
    )
    assert quote["can_place_order"] is True
    body = delivery_body(
        quote["total"],
        address={"entrance": "2", "floor": "3", "apartment": "12", "comment": "Домофон 12"},
        comment="Позвонить заранее",
        save_address=True,
    )
    created = ok(await api_client.post(f"{API}/orders", json=body, headers=customer | key()), 201)
    assert created["order_number"].startswith("OSH-")
    assert created["status"] == "pending"
    assert created["payment_method_code"] == "cash"
    assert created["payment_status"] == "pending"
    assert created["payment_due_at"] is None
    assert created["delivery_fee"] == "100.00"
    assert created["total_amount"] == quote["total"]
    assert Decimal(created["subtotal"]) + Decimal("100.00") == Decimal(created["total_amount"])

    order = (await demo.execute(select(Order).where(Order.id == created["id"]))).one()
    assert order.customer_phone == "+996700123456"  # normalized (DEC-89)
    assert order.language_code == "ru"
    assert order.delivery_address_text == "ул. Ленина, 1"
    assert (order.delivery_entrance, order.delivery_floor, order.delivery_apartment) == (
        "2",
        "3",
        "12",
    )
    assert order.customer_comment == "Позвонить заранее"

    item = (await demo.execute(select(OrderItem).where(OrderItem.order_id == order.id))).one()
    modifiers = (
        await demo.execute(
            select(OrderItemModifier).where(OrderItemModifier.order_item_id == item.id)
        )
    ).all()
    assert item.product_name == "Маргарита"
    assert item.special_instructions == "Без лука"
    # DEC-61: (size + Σ extra × qty) × quantity.
    per_unit = item.unit_price + sum(m.unit_price * m.quantity for m in modifiers)
    assert item.total_price == per_unit * item.quantity
    assert {m.group_name for m in modifiers} >= {"Тесто", "Добавки"}
    assert all(m.total_price == m.unit_price * m.quantity for m in modifiers)

    delivery = (await demo.execute(select(Delivery).where(Delivery.order_id == order.id))).one()
    assert delivery.delivery_comment == "Домофон 12"
    assert delivery.delivery_zone_id == await demo.scalar(select(DeliveryZone.id))

    payment = (await demo.execute(select(Payment).where(Payment.order_id == order.id))).one()
    cash_id = await demo.scalar(select(PaymentMethod.id).where(PaymentMethod.code == "cash"))
    assert (payment.status, payment.amount, payment.currency, payment.is_simulated) == (
        "pending",
        order.total_amount,
        "KGS",
        False,
    )
    assert payment.payment_method_id == cash_id and payment.paid_at is None

    history = (
        await demo.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
        )
    ).all()
    assert [(h.old_status, h.new_status) for h in history] == [(None, "pending")]

    assert await _count(demo, CartItem) == 0  # cart emptied
    saved = (await demo.execute(select(Address))).all()
    assert [a.address_text for a in saved] == ["ул. Ленина, 1"]


async def test_pickup_order_and_language_of_snapshots(
    api_client: httpx.AsyncClient, demo: AsyncConnection, clock: Clock
) -> None:
    ky_customer = await make_user(demo, RoleName.CUSTOMER.value, language="ky")
    await add_kompot(api_client, demo, ky_customer, 3)
    created = ok(
        await api_client.post(
            f"{API}/orders",
            json=order_body("420.00", language="uz"),
            headers=ky_customer | key(),
        ),
        201,
    )
    assert created["delivery_fee"] == "0.00" and created["delivery_type"] == "pickup"
    order = (await demo.execute(select(Order).where(Order.id == created["id"]))).one()
    assert order.language_code == "uz"
    assert order.delivery_address_text is None
    item = (await demo.execute(select(OrderItem).where(OrderItem.order_id == order.id))).one()
    assert item.product_name == "Kompot"  # DEC-15
    assert await _count(demo, Delivery) == 0


async def test_blocking_conditions_are_errors(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    async def place(body: dict) -> httpx.Response:
        return await api_client.post(f"{API}/orders", json=body, headers=customer | key())

    error(await place(order_body("0.00")), 422, "CART_EMPTY")
    await add_kompot(api_client, demo, customer, 2)  # 280
    body = error(await place(order_body("280.00")), 422, "MIN_ORDER_NOT_REACHED")
    assert body["details"]["min_order_amount"] == "300.00"
    await add_kompot(api_client, demo, customer, 2)  # 560
    error(await place(delivery_body("660.00", OUTSIDE)), 422, "OUT_OF_DELIVERY_ZONE")
    clock.now = CLOSED_AT
    body = error(await place(order_body("560.00")), 422, "RESTAURANT_CLOSED")
    assert body["details"]["next_opening_at"]
    assert await _count(demo, Order) == 0
    assert await _count(demo, IdempotencyKey) == 0  # errors are not stored (§14.2)
    assert await _count(demo, CartItem) == 1


async def test_request_validation(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)

    async def place(body: dict, headers: dict | None = None) -> httpx.Response:
        return await api_client.post(
            f"{API}/orders",
            json=body,
            headers=customer | (headers if headers is not None else key()),
        )

    # Idempotency-Key is required and checked (DEC-109).
    error(await place(order_body("420.00"), {}), 422, "VALIDATION_ERROR")
    error(
        await place(order_body("420.00"), {"Idempotency-Key": "bad key!"}), 422, "VALIDATION_ERROR"
    )
    # Unknown payment method (DEC-149: cash and mock_card are accepted).
    body = error(
        await place(order_body("420.00", payment_method_code="bitcoin")), 422, "VALIDATION_ERROR"
    )
    assert body["details"][0]["field"] == "payment_method_code"
    for bad in (
        order_body("420.00", customer_phone="12345"),
        order_body("420.00", customer_name="  "),
        order_body("420.00", customer_name="я" * 151),
        order_body("420.00", comment="я" * 501),
        order_body("420.00", address={"address_text": "x", **INSIDE}),
        order_body("420.00", save_address=True),
        order_body("420.00", subtotal="1.00"),
        order_body("1.001"),
        delivery_body("520.00", address={"address_text": "я" * 501}),
        delivery_body("520.00", address={"entrance": "я" * 31}),
        {**delivery_body("520.00"), "address_id": "00000000-0000-0000-0000-000000000000"},
    ):
        error(await place(bad), 422, "VALIDATION_ERROR")
    assert await _count(demo, Order) == 0


async def test_price_changed_is_reported_and_nothing_is_created(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)  # 420
    headers = customer | key()
    _, variant_id, _ = await variant_of(demo, "demo-drink-kompot", 1)
    await demo.execute(
        update(ProductVariant).where(ProductVariant.id == variant_id).values(price=150)
    )

    body = error(
        await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=headers),
        409,
        "PRICE_CHANGED",
    )
    assert body["details"]["total"] == "450.00"  # the current quote (DEC-10)
    assert await _count(demo, Order) == 0
    assert await _count(demo, CartItem) == 1

    # The same key may be used again after an error (§14.2 step 6).
    created = ok(
        await api_client.post(f"{API}/orders", json=order_body("450.00"), headers=headers), 201
    )
    assert created["total_amount"] == "450.00"


async def test_idempotent_replay_and_conflict(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    headers = customer | key()
    first = await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=headers)
    assert first.status_code == 201 and "Idempotent-Replayed" not in first.headers

    # Same key and body (phone written differently, same after normalization).
    again = await api_client.post(
        f"{API}/orders",
        json=order_body("420.00", customer_phone="+996700123456"),
        headers=headers,
    )
    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    assert await _count(demo, Order) == 1

    error(
        await api_client.post(
            f"{API}/orders", json=order_body("420.00", comment="другое"), headers=headers
        ),
        409,
        "IDEMPOTENCY_KEY_CONFLICT",
    )
    # Keys of different users do not conflict.
    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(
        await api_client.post(
            f"{API}/orders",
            json=order_body("420.00"),
            headers=other | {"Idempotency-Key": headers["Idempotency-Key"]},
        ),
        422,
        "CART_EMPTY",
    )


async def test_expired_key_is_replaced_but_valid_keys_stay(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    headers = customer | key()
    ok(await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=headers), 201)
    other_key = customer | key()
    await add_kompot(api_client, demo, customer, 3)
    ok(await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=other_key), 201)

    # The first key expires; the second one stays valid (DEC-148).
    await demo.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.key == headers["Idempotency-Key"])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await add_kompot(api_client, demo, customer, 4)
    new = ok(
        await api_client.post(f"{API}/orders", json=order_body("560.00"), headers=headers), 201
    )
    assert await _count(demo, Order) == 3
    keys = (await demo.execute(select(IdempotencyKey.key, IdempotencyKey.response_body))).all()
    assert len(keys) == 2
    by_key = {k: b for k, b in keys}
    assert by_key[headers["Idempotency-Key"]]["id"] == new["id"]
    assert other_key["Idempotency-Key"] in by_key


async def test_snapshots_do_not_follow_catalog_changes(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 4)
    created = ok(
        await api_client.post(
            f"{API}/orders", json=delivery_body("660.00"), headers=customer | key()
        ),
        201,
    )
    product_id, variant_id, _ = await variant_of(demo, "demo-drink-kompot", 1)
    await demo.execute(
        update(ProductVariant).where(ProductVariant.id == variant_id).values(price=999)
    )
    await demo.execute(
        update(ProductTranslation)
        .where(ProductTranslation.product_id == product_id)
        .values(name="Новое имя")
    )
    await demo.execute(update(DeliveryZone).values(delivery_fee=500))
    detail = ok(await api_client.get(f"{API}/orders/{created['id']}", headers=customer))
    assert detail["items"][0]["product_name"] == "Компот"
    assert detail["items"][0]["unit_price"] == "140.00"
    assert detail["delivery_fee"] == "100.00"
    assert detail["total_amount"] == "660.00"


# --------------------------------------------------------------------------
# Reading and cancellation requests
# --------------------------------------------------------------------------


async def test_orders_list_and_detail_belong_to_the_owner(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 4)
    created = ok(
        await api_client.post(
            f"{API}/orders",
            json=delivery_body("660.00", address={"comment": "Домофон 12"}),
            headers=customer | key(),
        ),
        201,
    )
    listing = ok(await api_client.get(f"{API}/orders", headers=customer))
    assert listing["pagination"] == {"page": 1, "page_size": 20, "total": 1, "pages": 1}
    assert listing["items"][0]["order_number"] == created["order_number"]
    assert listing["items"][0]["items_count"] == 4
    error(
        await api_client.get(f"{API}/orders", params={"page_size": 101}, headers=customer),
        422,
        "VALIDATION_ERROR",
    )

    detail = ok(await api_client.get(f"{API}/orders/{created['id']}", headers=customer))
    assert detail["address"]["comment"] == "Домофон 12"
    assert detail["address"]["latitude"] == INSIDE["latitude"]
    assert detail["payments"][0]["method_code"] == "cash"
    assert detail["payment_status"] == "pending"
    assert detail["status_history"][0]["new_status"] == "pending"
    assert detail["can_request_cancellation"] is True
    assert detail["customer_phone"] == "+996700123456"

    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(await api_client.get(f"{API}/orders/{created['id']}", headers=other), 404, "NOT_FOUND")
    assert ok(await api_client.get(f"{API}/orders", headers=other))["items"] == []
    admin = await make_user(demo, RoleName.ADMIN.value)
    error(await api_client.get(f"{API}/orders/{created['id']}", headers=admin), 403, "FORBIDDEN")


async def test_cancellation_requests(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    created = ok(
        await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=customer | key()),
        201,
    )
    url = f"{API}/orders/{created['id']}/cancellation-requests"

    for bad in ({}, {"reason": "   "}, {"reason": "я" * 501}):
        error(await api_client.post(url, json=bad, headers=customer), 422, "VALIDATION_ERROR")
    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(await api_client.post(url, json={"reason": "x"}, headers=other), 404, "NOT_FOUND")

    request = ok(
        await api_client.post(url, json={"reason": "  Передумал  "}, headers=customer), 201
    )
    assert (request["status"], request["reason"]) == ("pending", "Передумал")
    error(
        await api_client.post(url, json={"reason": "ещё раз"}, headers=customer),
        409,
        "CANCELLATION_REQUEST_PENDING",
    )
    detail = ok(await api_client.get(f"{API}/orders/{created['id']}", headers=customer))
    assert detail["can_request_cancellation"] is False
    assert detail["status"] == "pending"  # the customer never cancels directly

    # After a rejection a new request may be sent (DEC-42).
    await demo.execute(
        update(CancellationRequest).values(status="rejected", admin_comment="Уже готовим")
    )
    ok(await api_client.post(url, json={"reason": "Снова"}, headers=customer), 201)

    # Not allowed after `preparing` (DEC-38).
    await demo.execute(update(CancellationRequest).values(status="rejected"))
    await demo.execute(
        update(Order).where(Order.id == created["id"]).values(status="ready_for_pickup")
    )
    error(
        await api_client.post(url, json={"reason": "Поздно"}, headers=customer),
        409,
        "CANCELLATION_NOT_ALLOWED",
    )
    detail = ok(await api_client.get(f"{API}/orders/{created['id']}", headers=customer))
    assert detail["can_request_cancellation"] is False
    # Requests made in one test transaction share created_at: check as a set.
    assert "Уже готовим" in {r["admin_comment"] for r in detail["cancellation_requests"]}
