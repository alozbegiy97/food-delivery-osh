"""`POST /checkout/quote` (stage 6; API §6.1; DEC-17…DEC-22, DEC-102, DEC-147, DEC-148)."""

from datetime import UTC, datetime, time

import httpx
import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.catalog.models import ProductVariant
from app.modules.delivery.models import DeliveryZone
from app.modules.restaurant.models import RestaurantSettings, RestaurantWorkingHours
from app.modules.users.enums import RoleName
from app.modules.users.models import Address, User
from tests.orders_support import (
    API,
    CLOSED_AT,
    INSIDE,
    OUTSIDE,
    Clock,
    add_kompot,
    error,
    make_user,
    ok,
    variant_of,
)

pytestmark = pytest.mark.db


async def _quote(client: httpx.AsyncClient, headers: dict, body: dict, **params: str) -> dict:
    return ok(await client.post(f"{API}/checkout/quote", json=body, headers=headers, params=params))


def _codes(quote: dict) -> list[str]:
    return [problem["code"] for problem in quote["problems"]]


async def test_quote_requires_customer(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    error(await api_client.post(f"{API}/checkout/quote", json={}), 401, "UNAUTHORIZED")
    admin = await make_user(demo, RoleName.ADMIN.value)
    error(
        await api_client.post(
            f"{API}/checkout/quote", json={"delivery_type": "pickup"}, headers=admin
        ),
        403,
        "FORBIDDEN",
    )


async def test_pickup_quote_uses_global_minimum(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert _codes(quote) == ["CART_EMPTY"]
    assert quote["can_place_order"] is False

    await add_kompot(api_client, demo, customer, 2)  # 2 × 140 = 280 < 300
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert quote["subtotal"] == "280.00"
    assert quote["min_order_amount"] == "300.00"  # DEC-18
    assert quote["delivery_fee"] == "0.00"
    assert quote["zone"] is None
    assert _codes(quote) == ["MIN_ORDER_NOT_REACHED"]
    assert quote["problems"][0]["details"] == {"min_order_amount": "300.00", "subtotal": "280.00"}

    await add_kompot(api_client, demo, customer, 1)
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert quote["total"] == "420.00"
    assert quote["problems"] == [] and quote["can_place_order"] is True
    assert quote["is_open_now"] is True


async def test_delivery_quote_in_and_out_of_zone(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)  # 420
    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": INSIDE})
    assert quote["zone"]["name"].startswith("Демо-зона")
    assert quote["delivery_fee"] == "100.00"
    # The zone minimum (500) wins over the global one (DEC-17), without the fee (DEC-19).
    assert quote["min_order_amount"] == "500.00"
    assert quote["min_order_reached"] is False
    assert quote["total"] == "520.00"
    assert _codes(quote) == ["MIN_ORDER_NOT_REACHED"]

    await add_kompot(api_client, demo, customer, 1)  # 560
    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": INSIDE})
    assert quote["can_place_order"] is True and quote["total"] == "660.00"

    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": OUTSIDE})
    assert quote["zone"] is None
    assert _codes(quote) == ["OUT_OF_DELIVERY_ZONE"]


async def test_zone_without_own_minimum_uses_global_minimum(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await demo.execute(update(DeliveryZone).values(min_order_amount=0))
    await add_kompot(api_client, demo, customer, 3)  # 420 >= 300
    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": INSIDE})
    assert quote["min_order_amount"] == "300.00"
    assert quote["can_place_order"] is True


async def test_point_on_a_shared_border_takes_the_cheaper_zone(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    # A neighbour zone touching the demo zone along lon 72.86 (DEC-53 allows touching).
    await demo.execute(
        insert(DeliveryZone).values(
            name="Соседняя зона",
            delivery_fee=80,
            min_order_amount=0,
            is_active=True,
            boundary=func.ST_GeomFromText(
                "MULTIPOLYGON(((72.86 40.49, 72.95 40.49, 72.95 40.57, 72.86 40.57, 72.86 40.49)))",
                4326,
            ),
        )
    )
    await add_kompot(api_client, demo, customer, 4)
    border = {"latitude": "40.5300000", "longitude": "72.8600000"}
    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": border})
    assert quote["zone"]["name"] == "Соседняя зона"  # lower fee wins (DEC-102)
    assert quote["delivery_fee"] == "80.00"


async def test_closed_restaurant_and_overnight_hours(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    clock.now = CLOSED_AT  # 02:00 in Osh
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert quote["is_open_now"] is False
    assert _codes(quote) == ["RESTAURANT_CLOSED"]
    assert quote["problems"][0]["details"]["next_opening_at"].startswith("2026-11-12T10:00")

    # Wednesday 20:00 – 03:00: 02:00 on Thursday belongs to Wednesday (DEC-21).
    await demo.execute(
        update(RestaurantWorkingHours)
        .where(RestaurantWorkingHours.weekday == 2)
        .values(opens_at=time(20, 0), closes_at=time(3, 0), is_closed=False)
    )
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert quote["is_open_now"] is True and quote["can_place_order"] is True
    clock.now = datetime(2026, 11, 11, 21, 30, tzinfo=UTC)  # 03:30 – closed again
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert _codes(quote) == ["RESTAURANT_CLOSED"]


async def test_disabled_delivery_or_pickup(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 4)
    await demo.execute(update(RestaurantSettings).values(delivery_enabled=False))
    quote = await _quote(api_client, customer, {"delivery_type": "delivery", "address": INSIDE})
    assert quote["delivery_enabled"] is False
    assert _codes(quote) == ["DELIVERY_DISABLED"]
    assert (await _quote(api_client, customer, {"delivery_type": "pickup"}))["problems"] == []

    await demo.execute(update(RestaurantSettings).values(pickup_enabled=False))
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert _codes(quote) == ["PICKUP_DISABLED"]


async def test_unavailable_cart_line_is_a_problem(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    _, variant_id, _ = await variant_of(demo, "demo-drink-kompot", 1)
    await demo.execute(
        update(ProductVariant).where(ProductVariant.id == variant_id).values(is_available=False)
    )
    quote = await _quote(api_client, customer, {"delivery_type": "pickup"})
    assert quote["subtotal"] == "0.00"  # DEC-147
    assert _codes(quote)[0] == "ITEM_UNAVAILABLE"
    assert quote["problems"][0]["details"][0]["issues"][0]["code"] == "VARIANT_UNAVAILABLE"


async def test_quote_request_validation_and_saved_addresses(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    async def post(body: dict) -> httpx.Response:
        return await api_client.post(f"{API}/checkout/quote", json=body, headers=customer)

    error(await post({"delivery_type": "pickup", "address": INSIDE}), 422, "VALIDATION_ERROR")
    error(await post({"delivery_type": "delivery"}), 422, "VALIDATION_ERROR")
    error(
        await post({"delivery_type": "delivery", "address": {"latitude": "91", "longitude": "1"}}),
        422,
        "VALIDATION_ERROR",
    )

    await add_kompot(api_client, demo, customer, 4)
    saved = ok(
        await api_client.post(
            f"{API}/users/me/addresses",
            json={"address_text": "Дом", **INSIDE},
            headers=customer,
        ),
        201,
    )
    quote = ok(await post({"delivery_type": "delivery", "address_id": saved["id"]}))
    assert quote["delivery_fee"] == "100.00"

    no_point = ok(
        await api_client.post(
            f"{API}/users/me/addresses", json={"address_text": "Без точки"}, headers=customer
        ),
        201,
    )
    body = error(
        await post({"delivery_type": "delivery", "address_id": no_point["id"]}),
        422,
        "VALIDATION_ERROR",
    )
    assert body["details"][0]["field"] == "address_id"

    # Another customer's address is not found.
    other_user = await demo.scalar(select(User.id).where(User.full_name == "Покупатель").limit(1))
    assert other_user is not None
    foreign = await demo.scalar(
        insert(Address)
        .values(user_id=other_user, address_text="Чужой", latitude=40.53, longitude=72.8)
        .returning(Address.id)
    )
    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(
        await api_client.post(
            f"{API}/checkout/quote",
            json={"delivery_type": "delivery", "address_id": str(foreign)},
            headers=other,
        ),
        404,
        "NOT_FOUND",
    )
