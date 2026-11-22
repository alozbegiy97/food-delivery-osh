"""Server cart `/cart` (stage 5, API_SPECIFICATION.md §5, DEC-07/08/11/12/13/146).

Runs inside one rolled-back transaction (api_client). The catalog is built
through the admin API, so the cart sees exactly what the administrator set:
sizes, a required single dough group, a multiple extras group with limits,
a per-size extra price and later changes of availability and prices.
"""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import create_access_token, hash_password
from app.modules.cart.models import Cart, CartItem
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole
from app.seeds.base import seed_base

pytestmark = pytest.mark.db

API = "/api/v1"


def _ru(name: str) -> list[dict]:
    return [{"language_code": "ru", "name": name}]


async def _user(conn: AsyncConnection, *roles: str, language: str = "ru") -> dict[str, str]:
    role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=f"{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("correct1horse"),
            full_name="Покупатель",
            preferred_language=language,
        )
        .returning(User.id)
    )
    for role in roles:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_ids[role]))
    return {"Authorization": f"Bearer {create_access_token(user_id).token}"}


def _ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def _error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert body["code"] == code, body
    return body


class Menu:
    """Ids of the test catalog."""

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}

    def __getitem__(self, key: str) -> str:
        return self.ids[key]


@pytest.fixture
async def base(api_conn: AsyncConnection) -> AsyncConnection:
    await seed_base(api_conn)
    return api_conn


@pytest.fixture
async def admin(base: AsyncConnection) -> dict[str, str]:
    return await _user(base, RoleName.ADMIN.value)


@pytest.fixture
async def customer(base: AsyncConnection) -> dict[str, str]:
    return await _user(base, RoleName.CUSTOMER.value)


@pytest.fixture
async def menu(api_client: httpx.AsyncClient, admin: dict[str, str]) -> Menu:
    m = Menu()
    c = api_client

    async def post(path: str, body: object, status: int = 201) -> dict:
        return _ok(await c.post(f"{API}{path}", json=body, headers=admin), status)

    category = await post("/admin/categories", {"translations": _ru("Пицца")})
    tag = uuid.uuid4().hex[:6].upper()
    pizza = await post(
        "/admin/products",
        {
            "category_id": category["id"],
            "translations": [
                {"language_code": "ru", "name": "Маргарита"},
                {"language_code": "ky", "name": "Маргарита KY"},
            ],
            "variants": [{"sku": f"P30-{tag}", "price": "550.00", "translations": _ru("30 см")}],
        },
    )
    pizza = await post(
        f"/admin/products/{pizza['id']}/variants",
        {"sku": f"P40-{tag}", "price": "750.00", "translations": _ru("40 см"), "sort_order": 1},
    )
    m.ids["pizza"] = pizza["id"]
    m.ids["p30"] = next(v["id"] for v in pizza["variants"] if v["sku"].startswith("P30"))
    m.ids["p40"] = next(v["id"] for v in pizza["variants"] if v["sku"].startswith("P40"))

    dough = await post(
        "/admin/modifier-groups",
        {
            "translations": _ru("Тесто"),
            "selection_type": "single",
            "min_selections": 1,
            "max_selections": 1,
        },
    )
    extras = await post(
        "/admin/modifier-groups",
        {
            "translations": _ru("Добавки"),
            "selection_type": "multiple",
            "min_selections": 0,
            "max_selections": 2,
        },
    )
    m.ids["dough"], m.ids["extras"] = dough["id"], extras["id"]
    for key, group, name, price, max_quantity in (
        ("thin", dough, "Тонкое", "0", 1),
        ("thick", dough, "Пышное", "0", 1),
        ("cheese", extras, "Сыр", "50.00", 2),
        ("mushrooms", extras, "Грибы", "40.00", 1),
        ("jalapeno", extras, "Халапеньо", "30.00", 1),
    ):
        modifier = await post(
            "/admin/modifiers",
            {
                "group_id": group["id"],
                "translations": _ru(name),
                "price_delta": price,
                "max_quantity": max_quantity,
            },
        )
        m.ids[key] = modifier["id"]
    _ok(
        await c.put(
            f"{API}/admin/products/{m['pizza']}/modifier-groups",
            json=[
                {"group_id": m["dough"], "sort_order": 0},
                {"group_id": m["extras"], "sort_order": 1},
            ],
            headers=admin,
        )
    )
    # Cheese costs more on the 40 cm pizza (DATABASE_SCHEMA.md §5.6).
    _ok(
        await c.put(
            f"{API}/admin/variants/{m['p40']}/modifier-prices",
            json=[{"modifier_id": m["cheese"], "price_delta": "80.00"}],
            headers=admin,
        )
    )

    cola = await post(
        "/admin/products",
        {
            "category_id": category["id"],
            "translations": _ru("Кола"),
            "variants": [{"sku": f"COLA-{tag}", "price": "100.00", "translations": _ru("0,5 л")}],
        },
    )
    m.ids["cola"], m.ids["cola_v"] = cola["id"], cola["variants"][0]["id"]
    return m


def _pizza(menu: Menu, variant: str = "p30", quantity: int = 1, **extra: object) -> dict:
    body: dict = {
        "product_id": menu["pizza"],
        "variant_id": menu[variant],
        "quantity": quantity,
        "modifiers": [{"id": menu["thin"]}],
    }
    body.update(extra)
    return body


def _cola(menu: Menu, quantity: int = 1, **extra: object) -> dict:
    return {"product_id": menu["cola"], "variant_id": menu["cola_v"], "quantity": quantity, **extra}


async def _add(client: httpx.AsyncClient, headers: dict, body: dict) -> dict:
    return _ok(await client.post(f"{API}/cart/items", json=body, headers=headers))


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------


async def test_cart_requires_the_customer_role(
    api_client: httpx.AsyncClient, base: AsyncConnection, admin: dict
) -> None:
    _error(await api_client.get(f"{API}/cart"), 401, "UNAUTHORIZED")
    cook = await _user(base, RoleName.COOK.value)
    for headers in (admin, cook):
        _error(await api_client.get(f"{API}/cart", headers=headers), 403, "FORBIDDEN")
        _error(
            await api_client.post(f"{API}/cart/items", json={}, headers=headers), 403, "FORBIDDEN"
        )


async def test_empty_cart_is_returned_without_creating_a_row(
    api_client: httpx.AsyncClient, base: AsyncConnection, customer: dict
) -> None:
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert cart["items"] == []
    assert cart["items_count"] == 0
    assert cart["subtotal"] == "0.00"
    assert cart["currency"] == "KGS"
    assert cart["has_issues"] is False
    assert await base.scalar(select(func.count()).select_from(Cart)) == 0


# --------------------------------------------------------------------------
# Prices are calculated by the server
# --------------------------------------------------------------------------


async def test_prices_come_from_the_server_with_per_size_extra_price(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    body = _pizza(
        menu,
        "p40",
        quantity=2,
        modifiers=[{"id": menu["thick"]}, {"id": menu["cheese"], "quantity": 2}],
    )
    cart = await _add(api_client, customer, body)
    [item] = cart["items"]  # the only line so far
    # 750 + 0 (dough) + 80 (cheese override for 40 cm) × 2 = 910 per unit
    assert item["unit_price"] == "910.00"
    assert item["line_total"] == "1820.00"
    assert cart["subtotal"] == "1820.00"
    assert cart["items_count"] == 2
    assert item["product_name"] == "Маргарита"
    assert item["variant_name"] == "40 см"
    assert [(m["name"], m["quantity"], m["unit_price"]) for m in item["modifiers"]] == [
        ("Пышное", 1, "0.00"),
        ("Сыр", 2, "80.00"),
    ]
    assert item["modifiers"][1]["group_name"] == "Добавки"
    assert item["is_available"] is True and item["issues"] == []

    # The base extra price applies to the 30 cm size.
    cart = await _add(
        api_client, customer, _pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["cheese"]}])
    )
    # Lines added in one test transaction share created_at: find by size.
    small = next(i for i in cart["items"] if i["variant_id"] == menu["p30"])
    assert small["unit_price"] == "600.00"
    assert cart["subtotal"] == "2420.00"


async def test_client_prices_are_rejected(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    for extra in ({"price": "1.00"}, {"unit_price": "1.00"}, {"line_total": "1.00"}):
        _error(
            await api_client.post(f"{API}/cart/items", json=_cola(menu, **extra), headers=customer),
            422,
            "VALIDATION_ERROR",
        )
    response = await api_client.post(
        f"{API}/cart/items",
        json=_pizza(menu, modifiers=[{"id": menu["thin"], "price_delta": "0"}]),
        headers=customer,
    )
    _error(response, 422, "VALIDATION_ERROR")


async def test_names_follow_the_requested_language(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    await _add(api_client, customer, _pizza(menu))
    cart = _ok(await api_client.get(f"{API}/cart", params={"language": "ky"}, headers=customer))
    item = cart["items"][0]
    assert item["product_name"] == "Маргарита KY"
    # No KY translation of the size: falls back to RU.
    assert item["variant_name"] == "30 см"


# --------------------------------------------------------------------------
# Selection rules (§5.7, DEC-81)
# --------------------------------------------------------------------------


async def test_selection_rules_are_enforced(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    async def add(body: dict) -> httpx.Response:
        return await api_client.post(f"{API}/cart/items", json=body, headers=customer)

    # Required dough missing.
    error = _error(await add(_pizza(menu, modifiers=[])), 422, "MODIFIER_CONSTRAINT_VIOLATION")
    assert error["details"][0]["code"] == "GROUP_REQUIRED"
    assert error["details"][0]["group_name"] == "Тесто"
    # Two doughs in a single group.
    error = _error(
        await add(_pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["thick"]}])),
        422,
        "MODIFIER_CONSTRAINT_VIOLATION",
    )
    assert error["details"][0]["code"] == "GROUP_MAX_SELECTIONS"
    # Three different extras where at most two are allowed.
    three = [{"id": menu[k]} for k in ("thin", "cheese", "mushrooms", "jalapeno")]
    error = _error(await add(_pizza(menu, modifiers=three)), 422, "MODIFIER_CONSTRAINT_VIOLATION")
    assert error["details"][0] == {
        **error["details"][0],
        "code": "GROUP_MAX_SELECTIONS",
        "limit": 2,
    }
    # max_quantity of cheese is 2.
    error = _error(
        await add(
            _pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["cheese"], "quantity": 3}])
        ),
        422,
        "MODIFIER_CONSTRAINT_VIOLATION",
    )
    assert error["details"][0]["code"] == "MODIFIER_QUANTITY_EXCEEDED"
    assert error["details"][0]["limit"] == 2
    # A modifier of a group that is not linked to the product.
    error = _error(
        await add(_cola(menu, modifiers=[{"id": menu["cheese"]}])), 422, "ITEM_UNAVAILABLE"
    )
    assert error["details"][0]["code"] == "MODIFIER_UNAVAILABLE"
    # A size of another product.
    error = _error(await add({**_cola(menu), "variant_id": menu["p30"]}), 422, "ITEM_UNAVAILABLE")
    assert error["details"][0]["code"] == "VARIANT_UNAVAILABLE"
    # Unknown product.
    _error(await add({**_cola(menu), "product_id": str(uuid.uuid4())}), 422, "ITEM_UNAVAILABLE")
    # The same modifier twice in one request.
    _error(
        await add(_pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["thin"]}])),
        422,
        "VALIDATION_ERROR",
    )
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert cart["items"] == []


async def test_unavailable_things_cannot_be_added(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict, admin: dict
) -> None:
    async def patch(path: str, body: dict) -> None:
        _ok(await api_client.patch(f"{API}/admin/{path}", json=body, headers=admin))

    await patch(f"modifiers/{menu['mushrooms']}", {"is_available": False})
    _error(
        await api_client.post(
            f"{API}/cart/items",
            json=_pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["mushrooms"]}]),
            headers=customer,
        ),
        422,
        "ITEM_UNAVAILABLE",
    )
    await patch(f"variants/{menu['p40']}", {"is_available": False})
    _error(
        await api_client.post(f"{API}/cart/items", json=_pizza(menu, "p40"), headers=customer),
        422,
        "ITEM_UNAVAILABLE",
    )
    await patch(f"products/{menu['cola']}", {"is_available": False})
    _error(
        await api_client.post(f"{API}/cart/items", json=_cola(menu), headers=customer),
        422,
        "ITEM_UNAVAILABLE",
    )


# --------------------------------------------------------------------------
# Merge (DEC-11) and changes (DEC-12)
# --------------------------------------------------------------------------


async def test_identical_lines_are_merged(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    await _add(api_client, customer, _pizza(menu, special_instructions="Без  лука "))
    cart = await _add(
        api_client, customer, _pizza(menu, quantity=2, special_instructions=" Без лука")
    )
    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 3
    assert cart["items"][0]["special_instructions"] == "Без лука"

    # Different instructions, size or extras: separate lines.
    await _add(api_client, customer, _pizza(menu, special_instructions="Острое"))
    await _add(api_client, customer, _pizza(menu, "p40", special_instructions="Без лука"))
    cart = await _add(
        api_client,
        customer,
        _pizza(
            menu,
            modifiers=[{"id": menu["thin"]}, {"id": menu["cheese"]}],
            special_instructions="Без лука",
        ),
    )
    assert len(cart["items"]) == 4
    # Same extras with another quantity are another line too.
    cart = await _add(
        api_client,
        customer,
        _pizza(
            menu,
            modifiers=[{"id": menu["cheese"], "quantity": 2}, {"id": menu["thin"]}],
            special_instructions="Без лука",
        ),
    )
    assert len(cart["items"]) == 5
    # Modifier order in the request does not matter.
    cart = await _add(
        api_client,
        customer,
        _pizza(
            menu,
            modifiers=[{"id": menu["cheese"]}, {"id": menu["thin"]}],
            special_instructions="Без лука",
        ),
    )
    assert len(cart["items"]) == 5
    assert cart["items_count"] == 3 + 1 + 1 + 2 + 1


async def test_patch_changes_only_quantity_and_instructions_and_merges(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    first = (await _add(api_client, customer, _pizza(menu, special_instructions="Острое")))[
        "items"
    ][0]
    cart = await _add(api_client, customer, _pizza(menu, quantity=2))
    second = next(i for i in cart["items"] if i["id"] != first["id"])

    url = f"{API}/cart/items/{first['id']}"
    cart = _ok(await api_client.patch(url, json={"quantity": 4}, headers=customer))
    assert next(i for i in cart["items"] if i["id"] == first["id"])["quantity"] == 4
    assert cart["subtotal"] == "3300.00"  # (4 + 2) × 550

    # Only quantity and special_instructions may change (DEC-12).
    for body in ({"variant_id": menu["p40"]}, {"modifiers": []}, {}, {"quantity": None}):
        _error(await api_client.patch(url, json=body, headers=customer), 422, "VALIDATION_ERROR")

    # Clearing the instructions makes it equal to the second line: merged.
    cart = _ok(await api_client.patch(url, json={"special_instructions": None}, headers=customer))
    assert len(cart["items"]) == 1
    assert cart["items"][0]["id"] == second["id"]
    assert cart["items"][0]["quantity"] == 6


async def test_line_and_cart_limits(
    api_client: httpx.AsyncClient, base: AsyncConnection, menu: Menu, customer: dict
) -> None:
    async def add(body: dict) -> httpx.Response:
        return await api_client.post(f"{API}/cart/items", json=body, headers=customer)

    for quantity in (0, 100):
        _error(await add(_cola(menu, quantity)), 422, "VALIDATION_ERROR")
    _error(await add(_cola(menu, special_instructions="я" * 501)), 422, "VALIDATION_ERROR")
    cart = _ok(await add(_cola(menu, 2, special_instructions="я" * 500)))
    line_id = cart["items"][0]["id"]

    await _add(api_client, customer, _cola(menu, 98))
    error = _error(await add(_cola(menu, 2)), 422, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "quantity"
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert {i["quantity"] for i in cart["items"]} == {2, 98}

    # A merge through PATCH may not exceed 99 either (2 + 98).
    _error(
        await api_client.patch(
            f"{API}/cart/items/{line_id}", json={"special_instructions": ""}, headers=customer
        ),
        422,
        "VALIDATION_ERROR",
    )

    # At most 50 different lines.
    for number in range(48):
        _ok(await add(_cola(menu, special_instructions=f"#{number}")))
    error = _error(await add(_cola(menu, special_instructions="51")), 422, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "cart"
    assert await base.scalar(select(func.count()).select_from(CartItem)) == 50


async def test_delete_line_and_clear_cart(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict
) -> None:
    await _add(api_client, customer, _pizza(menu))
    cart = await _add(api_client, customer, _cola(menu, 3))
    cola = next(i for i in cart["items"] if i["product_id"] == menu["cola"])
    _ok(await api_client.delete(f"{API}/cart/items/{cola['id']}", headers=customer), 204)
    _error(
        await api_client.delete(f"{API}/cart/items/{cola['id']}", headers=customer),
        404,
        "NOT_FOUND",
    )
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert [i["product_id"] for i in cart["items"]] == [menu["pizza"]]
    _ok(await api_client.delete(f"{API}/cart", headers=customer), 204)
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert cart["items"] == [] and cart["subtotal"] == "0.00"
    # Clearing an already empty cart is fine.
    _ok(await api_client.delete(f"{API}/cart", headers=customer), 204)


async def test_another_customer_cannot_touch_my_lines(
    api_client: httpx.AsyncClient, base: AsyncConnection, menu: Menu, customer: dict
) -> None:
    cart = await _add(api_client, customer, _cola(menu))
    line_id = cart["items"][0]["id"]
    other = await _user(base, RoleName.CUSTOMER.value)
    _error(
        await api_client.patch(f"{API}/cart/items/{line_id}", json={"quantity": 5}, headers=other),
        404,
        "NOT_FOUND",
    )
    _error(await api_client.delete(f"{API}/cart/items/{line_id}", headers=other), 404, "NOT_FOUND")
    _ok(await api_client.delete(f"{API}/cart", headers=other), 204)
    assert _ok(await api_client.get(f"{API}/cart", headers=other))["items"] == []
    mine = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert mine["items"][0]["quantity"] == 1


# --------------------------------------------------------------------------
# Stored lines are re-priced and re-validated on every read
# --------------------------------------------------------------------------


async def test_cart_reflects_catalog_changes(
    api_client: httpx.AsyncClient, menu: Menu, customer: dict, admin: dict
) -> None:
    await _add(
        api_client,
        customer,
        _pizza(menu, modifiers=[{"id": menu["thin"]}, {"id": menu["mushrooms"]}]),
    )
    await _add(api_client, customer, _cola(menu, 2))

    _ok(
        await api_client.patch(
            f"{API}/admin/variants/{menu['cola_v']}", json={"price": "120.00"}, headers=admin
        )
    )
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    assert cart["subtotal"] == str(Decimal("590.00") + Decimal("240.00"))

    _ok(
        await api_client.patch(
            f"{API}/admin/modifiers/{menu['mushrooms']}",
            json={"is_available": False},
            headers=admin,
        )
    )
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    pizza = next(i for i in cart["items"] if i["product_id"] == menu["pizza"])
    assert pizza["is_available"] is False
    assert pizza["issues"][0]["code"] == "MODIFIER_UNAVAILABLE"
    assert pizza["issues"][0]["modifier_name"] == "Грибы"
    assert cart["has_issues"] is True
    # Only lines without issues are counted in the subtotal.
    assert cart["subtotal"] == "240.00"
    assert cart["items_count"] == 3

    _ok(await api_client.delete(f"{API}/admin/products/{menu['cola']}", headers=admin), 204)
    cart = _ok(await api_client.get(f"{API}/cart", headers=customer))
    cola = next(i for i in cart["items"] if i["product_id"] == menu["cola"])
    assert cola["issues"][0]["code"] == "PRODUCT_UNAVAILABLE"
    assert cart["subtotal"] == "0.00"

    # The customer removes the broken line; the quantity can still be changed.
    _ok(
        await api_client.patch(
            f"{API}/cart/items/{cola['id']}", json={"quantity": 1}, headers=customer
        )
    )
    _ok(await api_client.delete(f"{API}/cart/items/{pizza['id']}", headers=customer), 204)
