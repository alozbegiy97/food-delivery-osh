"""`/users/me/addresses` (stage 6; API §4; DATABASE_SCHEMA.md §3.5; DEC-01, DEC-23, DEC-148)."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.users.enums import RoleName
from tests.orders_support import API, INSIDE, error, make_user, ok

pytestmark = pytest.mark.db

URL = f"{API}/users/me/addresses"


async def test_addresses_need_the_customer_role(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    error(await api_client.get(URL), 401, "UNAUTHORIZED")
    cook = await make_user(demo, RoleName.COOK.value)
    error(await api_client.get(URL, headers=cook), 403, "FORBIDDEN")


async def test_crud_default_and_ownership(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict
) -> None:
    home = ok(
        await api_client.post(
            URL,
            json={
                "label": " Дом ",
                "address_text": "  ул. Ленина, 1 ",
                **INSIDE,
                "entrance": "2",
                "floor": "3",
                "apartment": "12",
                "comment": "Домофон 12",
                "is_default": True,
            },
            headers=customer,
        ),
        201,
    )
    assert (home["label"], home["address_text"], home["is_default"]) == (
        "Дом",
        "ул. Ленина, 1",
        True,
    )
    assert home["latitude"] == INSIDE["latitude"]
    work = ok(
        await api_client.post(
            URL, json={"address_text": "Работа", "is_default": True}, headers=customer
        ),
        201,
    )
    assert work["latitude"] is None  # allowed in the book, not for delivery (DEC-01)

    listing = ok(await api_client.get(URL, headers=customer))
    assert [a["address_text"] for a in listing["items"]] == ["Работа", "ул. Ленина, 1"]
    assert [a["is_default"] for a in listing["items"]] == [True, False]  # one default
    assert listing["pagination"]["total"] == 2

    moved = ok(await api_client.post(f"{URL}/{home['id']}/default", headers=customer))
    assert moved["is_default"] is True
    listing = ok(await api_client.get(URL, headers=customer))
    assert {a["id"]: a["is_default"] for a in listing["items"]} == {
        home["id"]: True,
        work["id"]: False,
    }

    patched = ok(
        await api_client.patch(
            f"{URL}/{work['id']}",
            json={"comment": "3 этаж", **INSIDE, "label": None},
            headers=customer,
        )
    )
    assert (patched["comment"], patched["latitude"], patched["label"]) == (
        "3 этаж",
        INSIDE["latitude"],
        None,
    )
    assert patched["address_text"] == "Работа"

    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(
        await api_client.patch(f"{URL}/{home['id']}", json={"label": "x"}, headers=other),
        404,
        "NOT_FOUND",
    )
    error(await api_client.delete(f"{URL}/{home['id']}", headers=other), 404, "NOT_FOUND")
    error(await api_client.post(f"{URL}/{home['id']}/default", headers=other), 404, "NOT_FOUND")
    assert ok(await api_client.get(URL, headers=other))["items"] == []

    ok(await api_client.delete(f"{URL}/{home['id']}", headers=customer), 204)
    error(await api_client.delete(f"{URL}/{home['id']}", headers=customer), 404, "NOT_FOUND")
    assert [a["id"] for a in ok(await api_client.get(URL, headers=customer))["items"]] == [
        work["id"]
    ]


async def test_address_limits_and_coordinates(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict
) -> None:
    async def create(body: dict) -> httpx.Response:
        return await api_client.post(URL, json=body, headers=customer)

    base = {"address_text": "ул. Ленина, 1"}
    for bad in (
        {},
        {"address_text": "   "},
        {"address_text": "я" * 501},
        {**base, "label": "я" * 81},
        {**base, "entrance": "я" * 31},
        {**base, "floor": "я" * 21},
        {**base, "apartment": "я" * 31},
        {**base, "comment": "я" * 501},
        {**base, "latitude": "40.5"},  # without longitude
        {**base, "latitude": "91", "longitude": "72.8"},
        {**base, "latitude": "40.5", "longitude": "181"},
        {**base, "latitude": "40.12345678", "longitude": "72.8"},  # > 7 places
        {**base, "user_id": "00000000-0000-0000-0000-000000000000"},
    ):
        error(await create(bad), 422, "VALIDATION_ERROR")
    ok(
        await create(
            {
                "address_text": "я" * 500,
                "label": "я" * 80,
                "entrance": "я" * 30,
                "floor": "я" * 20,
                "apartment": "я" * 30,
                "comment": "я" * 500,
            }
        ),
        201,
    )
    created = ok(await create(base), 201)
    for bad in ({}, {"address_text": None}, {"latitude": "40.5"}, {"is_default": None}):
        error(
            await api_client.patch(f"{URL}/{created['id']}", json=bad, headers=customer),
            422,
            "VALIDATION_ERROR",
        )
    cleared = ok(
        await api_client.patch(
            f"{URL}/{created['id']}", json={"latitude": None, "longitude": None}, headers=customer
        )
    )
    assert cleared["latitude"] is None
