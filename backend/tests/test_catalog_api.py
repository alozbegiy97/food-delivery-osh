"""Public catalog and restaurant API on the real demo catalog (stage 4A).

The `base` and `demo` seeds run inside the test's rolled-back transaction,
then the API reads exactly those rows through `api_client`.
"""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.catalog.models import (
    Category,
    Modifier,
    Product,
    ProductTranslation,
    ProductVariant,
)
from app.seeds.base import seed_base
from app.seeds.demo import seed_demo

pytestmark = pytest.mark.db

API = "/api/v1"


@pytest.fixture
async def demo(api_conn: AsyncConnection) -> AsyncConnection:
    await seed_base(api_conn)
    await seed_demo(api_conn)
    return api_conn


async def _product_id(conn: AsyncConnection, slug_suffix: str) -> uuid.UUID:
    product_id = await conn.scalar(select(Product.id).where(Product.slug.endswith(slug_suffix)))
    assert product_id is not None
    return product_id


async def _get(client: httpx.AsyncClient, path: str, **params: object) -> httpx.Response:
    return await client.get(f"{API}{path}", params=params)


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------


async def test_categories_come_from_database(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    response = await _get(api_client, "/catalog/categories")
    assert response.status_code == 200
    items = response.json()["items"]
    expected = await demo.scalar(
        select(func.count()).select_from(Category).where(Category.is_active)
    )
    assert len(items) == expected == 8
    assert items[0]["name"] == "Пицца"  # sort_order 0, Russian by default
    assert [item["sort_order"] for item in items] == sorted(item["sort_order"] for item in items)


async def test_categories_language_and_inactive(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    uz = (await _get(api_client, "/catalog/categories", language="uz")).json()["items"]
    assert uz[0]["name"] == "Pitsa"
    await demo.execute(
        update(Category).where(Category.slug.endswith("pizza")).values(is_active=False)
    )
    items = (await _get(api_client, "/catalog/categories")).json()["items"]
    assert len(items) == 7
    assert all(not item["slug"].endswith("pizza") for item in items)


async def test_unknown_language_is_rejected(api_client: httpx.AsyncClient) -> None:
    response = await _get(api_client, "/catalog/categories", language="en")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------
# Product list
# --------------------------------------------------------------------------


async def test_product_list_with_pagination(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    first = (await _get(api_client, "/catalog/products", page_size=5)).json()
    assert first["pagination"] == {"page": 1, "page_size": 5, "total": 21, "pages": 5}
    assert len(first["items"]) == 5
    last = (await _get(api_client, "/catalog/products", page_size=5, page=5)).json()
    assert len(last["items"]) == 1
    ids = set()
    for page in range(1, 6):
        ids |= {
            item["id"]
            for item in (
                await _get(api_client, "/catalog/products", page_size=5, page=page)
            ).json()["items"]
        }
    assert len(ids) == 21


async def test_price_from_is_lowest_available_variant(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    product_id = await _product_id(demo, "pizza-margherita")
    category_id = await demo.scalar(select(Product.category_id).where(Product.id == product_id))
    items = (await _get(api_client, "/catalog/products", category_id=str(category_id))).json()[
        "items"
    ]
    margherita = next(item for item in items if item["id"] == str(product_id))
    assert margherita["price_from"] == "550.00"  # money as a decimal string
    assert margherita["is_available"] is True
    assert margherita["name"] == "Маргарита"

    cheapest = await demo.scalar(
        select(ProductVariant.id)
        .where(ProductVariant.product_id == product_id)
        .order_by(ProductVariant.price)
        .limit(1)
    )
    await demo.execute(
        update(ProductVariant).where(ProductVariant.id == cheapest).values(is_available=False)
    )
    detail = (await _get(api_client, f"/catalog/products/{product_id}")).json()
    assert detail["price_from"] == "750.00"

    await demo.execute(
        update(ProductVariant)
        .where(ProductVariant.product_id == product_id)
        .values(is_available=False)
    )
    detail = (await _get(api_client, f"/catalog/products/{product_id}")).json()
    assert detail["price_from"] is None
    assert detail["is_available"] is False  # shown, but not orderable


async def test_filters_category_featured_and_search(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    pizza_category = await demo.scalar(select(Category.id).where(Category.slug.endswith("pizza")))
    pizzas = (await _get(api_client, "/catalog/products", category_id=str(pizza_category))).json()
    assert pizzas["pagination"]["total"] == 3
    assert {item["category_id"] for item in pizzas["items"]} == {str(pizza_category)}

    found = (await _get(api_client, "/catalog/products", search="маргар")).json()["items"]
    assert [item["name"] for item in found] == ["Маргарита"]
    nothing = (await _get(api_client, "/catalog/products", search="100%_")).json()
    assert nothing["pagination"]["total"] == 0  # LIKE wildcards are escaped

    product_id = await _product_id(demo, "pizza-four-cheese")
    await demo.execute(update(Product).where(Product.id == product_id).values(is_featured=True))
    featured = (await _get(api_client, "/catalog/products", featured="true")).json()["items"]
    assert str(product_id) in {item["id"] for item in featured}
    assert all(item["is_featured"] for item in featured)


async def test_deleted_products_and_inactive_categories_are_hidden(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    product_id = await _product_id(demo, "pizza-margherita")
    await demo.execute(
        update(Product).where(Product.id == product_id).values(deleted_at=func.now())
    )
    listing = (await _get(api_client, "/catalog/products", page_size=100)).json()
    assert listing["pagination"]["total"] == 20
    assert str(product_id) not in {item["id"] for item in listing["items"]}
    assert (await _get(api_client, f"/catalog/products/{product_id}")).status_code == 404

    other = await _product_id(demo, "pizza-pepperoni-beef")
    await demo.execute(
        update(Category).where(Category.slug.endswith("pizza")).values(is_active=False)
    )
    response = await _get(api_client, f"/catalog/products/{other}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_unknown_product_is_404(api_client: httpx.AsyncClient) -> None:
    assert (await _get(api_client, f"/catalog/products/{uuid.uuid4()}")).status_code == 404
    assert (await _get(api_client, "/catalog/products/not-a-uuid")).status_code == 422


# --------------------------------------------------------------------------
# Product detail: sizes, dough, extras
# --------------------------------------------------------------------------


async def test_pizza_detail_has_sizes_dough_and_extras(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    product_id = await _product_id(demo, "pizza-margherita")
    detail = (await _get(api_client, f"/catalog/products/{product_id}")).json()

    assert [(v["price"], v["is_available"]) for v in detail["variants"]] == [
        ("550.00", True),
        ("750.00", True),
    ]
    dough, extras = detail["modifier_groups"]
    assert dough["selection_type"] == "single"
    assert dough["is_required"] is True
    assert (dough["min_selections"], dough["max_selections"]) == (1, 1)
    assert len(dough["modifiers"]) >= 2
    assert extras["selection_type"] == "multiple"
    assert extras["is_required"] is False

    big = detail["variants"][1]["id"]
    overridden = [m for m in extras["modifiers"] if m["variant_prices"]]
    assert overridden, "40 cm extras have their own prices"
    for modifier in overridden:
        assert [p["variant_id"] for p in modifier["variant_prices"]] == [big]
        assert Decimal(modifier["variant_prices"][0]["price_delta"]) > Decimal(
            modifier["price_delta"]
        )


async def test_unavailable_modifier_is_shown_as_unavailable(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    product_id = await _product_id(demo, "pizza-margherita")
    detail = (await _get(api_client, f"/catalog/products/{product_id}")).json()
    modifier_id = detail["modifier_groups"][1]["modifiers"][0]["id"]
    await demo.execute(
        update(Modifier).where(Modifier.id == modifier_id).values(is_available=False)
    )
    detail = (await _get(api_client, f"/catalog/products/{product_id}")).json()
    modifier = next(m for m in detail["modifier_groups"][1]["modifiers"] if m["id"] == modifier_id)
    assert modifier["is_available"] is False


async def test_translation_fallback(api_client: httpx.AsyncClient, demo: AsyncConnection) -> None:
    product_id = await _product_id(demo, "pizza-margherita")
    ky = (await _get(api_client, f"/catalog/products/{product_id}", language="ky")).json()
    ru = (await _get(api_client, f"/catalog/products/{product_id}", language="ru")).json()
    assert ky["name"] and ru["name"] == "Маргарита"

    # No KY translation -> Russian (DATABASE_SCHEMA.md §2.2).
    await demo.execute(
        ProductTranslation.__table__.delete().where(
            ProductTranslation.product_id == product_id, ProductTranslation.language_code == "ky"
        )
    )
    assert (await _get(api_client, f"/catalog/products/{product_id}", language="ky")).json()[
        "name"
    ] == "Маргарита"
    # Only UZ left -> the first available translation.
    await demo.execute(
        ProductTranslation.__table__.delete().where(
            ProductTranslation.product_id == product_id, ProductTranslation.language_code == "ru"
        )
    )
    uz_name = await demo.scalar(
        select(ProductTranslation.name).where(ProductTranslation.product_id == product_id)
    )
    assert (await _get(api_client, f"/catalog/products/{product_id}", language="ky")).json()[
        "name"
    ] == uz_name


async def test_user_preferred_language_is_used(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    response = await api_client.post(
        f"{API}/auth/register",
        json={
            "email": "lang@example.com",
            "password": "correct1horse",
            "full_name": "Lang",
            "preferred_language": "uz",
        },
    )
    access = response.json()["access_token"]
    items = (
        await api_client.get(
            f"{API}/catalog/categories", headers={"Authorization": f"Bearer {access}"}
        )
    ).json()["items"]
    assert items[0]["name"] == "Pitsa"
    # An explicit parameter wins over the user's language.
    items = (
        await api_client.get(
            f"{API}/catalog/categories",
            params={"language": "ru"},
            headers={"Authorization": f"Bearer {access}"},
        )
    ).json()["items"]
    assert items[0]["name"] == "Пицца"
    # A broken token on a public endpoint is ignored, not an error.
    response = await api_client.get(
        f"{API}/catalog/categories", headers={"Authorization": "Bearer broken"}
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------
# Restaurant
# --------------------------------------------------------------------------


async def test_restaurant_info(api_client: httpx.AsyncClient, demo: AsyncConnection) -> None:
    response = await _get(api_client, "/restaurant")
    assert response.status_code == 200
    body = response.json()
    assert body["name"]
    assert body["timezone"] == "Asia/Bishkek"
    assert len(body["working_hours"]) == 7
    assert [day["weekday"] for day in body["working_hours"]] == list(range(7))
    assert isinstance(body["is_open_now"], bool)
    if body["is_open_now"]:
        assert body["next_opening_at"] is None
    else:
        assert body["next_opening_at"] is not None
    assert body["min_order_amount"].count(".") == 1  # decimal string


async def test_restaurant_without_settings_fails_loudly(api_client: httpx.AsyncClient) -> None:
    response = await _get(api_client, "/restaurant")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
