"""Catalog administration `/admin` (stage 4B, API_SPECIFICATION.md §9).

Runs inside one rolled-back transaction (api_client). Each scenario checks
the admin answer and, where it matters, what the public catalog (4A/4C)
shows afterwards. Uploaded files go to the temporary MEDIA_ROOT of tests.
"""

import io
import os
import uuid
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import create_access_token, hash_password
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole
from app.seeds.base import seed_base
from app.seeds.demo import seed_demo

pytestmark = pytest.mark.db

API = "/api/v1"
RU = {"language_code": "ru", "name": "Пицца"}


async def _user_with_roles(conn: AsyncConnection, *roles: str) -> dict[str, str]:
    role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=f"{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("correct1horse"),
            full_name="Staff",
        )
        .returning(User.id)
    )
    for role in roles:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_ids[role]))
    return {"Authorization": f"Bearer {create_access_token(user_id).token}"}


@pytest.fixture
async def base(api_conn: AsyncConnection) -> AsyncConnection:
    await seed_base(api_conn)
    return api_conn


@pytest.fixture
async def admin(base: AsyncConnection) -> dict[str, str]:
    return await _user_with_roles(base, RoleName.ADMIN.value)


def _error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert body["code"] == code
    return body


def _png(width: int = 8, height: int = 8, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 80, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


async def _category(client: httpx.AsyncClient, admin: dict, name: str = "Пицца") -> dict:
    response = await client.post(
        f"{API}/admin/categories",
        json={"translations": [{"language_code": "ru", "name": name}]},
        headers=admin,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _variant(sku: str, price: str = "550.00", name: str = "30 см") -> dict:
    return {"sku": sku, "price": price, "translations": [{"language_code": "ru", "name": name}]}


async def _product(client: httpx.AsyncClient, admin: dict, category_id: str, **extra) -> dict:
    body = {
        "category_id": category_id,
        "translations": [{"language_code": "ru", "name": "Маргарита", "description": "Классика"}],
        "variants": [_variant(f"SKU-{uuid.uuid4().hex[:8]}")],
        **extra,
    }
    response = await client.post(f"{API}/admin/products", json=body, headers=admin)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------


async def test_only_admin_may_use_catalog_admin(
    api_client: httpx.AsyncClient, base: AsyncConnection
) -> None:
    _error(await api_client.get(f"{API}/admin/categories"), 401, "UNAUTHORIZED")
    customer = await _user_with_roles(base, RoleName.CUSTOMER.value)
    cook = await _user_with_roles(base, RoleName.COOK.value)
    for headers in (customer, cook):
        _error(await api_client.get(f"{API}/admin/products", headers=headers), 403, "FORBIDDEN")
        _error(
            await api_client.post(
                f"{API}/admin/categories", json={"translations": [RU]}, headers=headers
            ),
            403,
            "FORBIDDEN",
        )


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------


async def test_category_create_slug_and_translations(
    api_client: httpx.AsyncClient, admin: dict
) -> None:
    first = await _category(api_client, admin, "Пицца")
    assert first["slug"] == "pitstsa"  # from the Russian name (DEC-145)
    assert first["translations"] == [{"language_code": "ru", "name": "Пицца", "description": None}]
    assert first["is_active"] is True and first["products_count"] == 0
    second = await _category(api_client, admin, "Пицца")
    assert second["slug"] == "pitstsa-2"

    custom = await api_client.post(
        f"{API}/admin/categories",
        json={
            "slug": "hot-pizza",
            "translations": [
                {"language_code": "uz", "name": "Pitsa"},
                {"language_code": "ru", "name": "Горячая пицца"},
                {"language_code": "ky", "name": "Ысык пицца"},
            ],
        },
        headers=admin,
    )
    assert custom.status_code == 201
    assert [t["language_code"] for t in custom.json()["translations"]] == ["ru", "ky", "uz"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"translations": [{"language_code": "ky", "name": "Пицца"}]}, id="no-ru"),
        pytest.param({"translations": [RU, RU]}, id="duplicate-language"),
        pytest.param({"translations": [{"language_code": "ru", "name": "   "}]}, id="blank-name"),
        pytest.param({"translations": [RU], "slug": "Bad Slug"}, id="bad-slug"),
        pytest.param(
            {"translations": [{"language_code": "en", "name": "Pizza"}]}, id="unknown-language"
        ),
        pytest.param({"translations": [RU], "role": "admin"}, id="unknown-field"),
    ],
)
async def test_category_validation(api_client: httpx.AsyncClient, admin: dict, body: dict) -> None:
    _error(
        await api_client.post(f"{API}/admin/categories", json=body, headers=admin),
        422,
        "VALIDATION_ERROR",
    )


async def test_category_taken_slug(api_client: httpx.AsyncClient, admin: dict) -> None:
    await _category(api_client, admin, "Пицца")
    error = _error(
        await api_client.post(
            f"{API}/admin/categories", json={"translations": [RU], "slug": "pitstsa"}, headers=admin
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert error["details"][0]["field"] == "slug"


async def test_category_update_and_deactivate(api_client: httpx.AsyncClient, admin: dict) -> None:
    category = await _category(api_client, admin)
    product = await _product(api_client, admin, category["id"])
    updated = await api_client.patch(
        f"{API}/admin/categories/{category['id']}",
        json={
            "sort_order": 5,
            "translations": [RU, {"language_code": "ky", "name": "Пицца KY", "description": "Д"}],
        },
        headers=admin,
    )
    assert updated.status_code == 200
    assert updated.json()["sort_order"] == 5
    assert len(updated.json()["translations"]) == 2
    public = (await api_client.get(f"{API}/catalog/categories", params={"language": "ky"})).json()
    assert {"Пицца KY"} <= {c["name"] for c in public["items"]}

    # DELETE = deactivation (DEC-26): hidden publicly, still listed for the admin.
    assert (
        await api_client.delete(f"{API}/admin/categories/{category['id']}", headers=admin)
    ).status_code == 204
    public = (await api_client.get(f"{API}/catalog/categories")).json()
    assert category["id"] not in {c["id"] for c in public["items"]}
    assert (await api_client.get(f"{API}/catalog/products/{product['id']}")).status_code == 404
    admin_list = (await api_client.get(f"{API}/admin/categories", headers=admin)).json()["items"]
    row = next(c for c in admin_list if c["id"] == category["id"])
    assert row["is_active"] is False and row["products_count"] == 1
    # Reactivation through PATCH.
    await api_client.patch(
        f"{API}/admin/categories/{category['id']}", json={"is_active": True}, headers=admin
    )
    assert (await api_client.get(f"{API}/catalog/products/{product['id']}")).status_code == 200


async def test_unknown_category_is_404(api_client: httpx.AsyncClient, admin: dict) -> None:
    _error(
        await api_client.patch(
            f"{API}/admin/categories/{uuid.uuid4()}", json={"sort_order": 1}, headers=admin
        ),
        404,
        "NOT_FOUND",
    )


# --------------------------------------------------------------------------
# Products and variants
# --------------------------------------------------------------------------


async def test_product_create_requires_variant_and_shows_publicly(
    api_client: httpx.AsyncClient, admin: dict
) -> None:
    category = await _category(api_client, admin)
    no_variants = {"category_id": category["id"], "translations": [RU], "variants": []}
    _error(
        await api_client.post(f"{API}/admin/products", json=no_variants, headers=admin),
        422,
        "VALIDATION_ERROR",
    )

    product = await _product(api_client, admin, category["id"], is_featured=True)
    assert product["slug"] == "margarita"
    assert len(product["variants"]) == 1
    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    assert public["name"] == "Маргарита" and public["description"] == "Классика"
    assert public["price_from"] == "550.00" and public["is_featured"] is True


async def test_product_validation(api_client: httpx.AsyncClient, admin: dict) -> None:
    category = await _category(api_client, admin)
    base = {"category_id": category["id"], "translations": [RU]}
    cases = [
        {**base, "category_id": str(uuid.uuid4()), "variants": [_variant("A-1")]},
        {**base, "variants": [_variant("A-1"), _variant("a-1")]},  # duplicate SKU in request
        {**base, "variants": [_variant("A 1")]},  # bad SKU characters
        {**base, "variants": [_variant("A-2", price="-1")]},
        {**base, "variants": [_variant("A-3", price="1.005")]},
    ]
    for body in cases:
        _error(
            await api_client.post(f"{API}/admin/products", json=body, headers=admin),
            422,
            "VALIDATION_ERROR",
        )
    await _product(api_client, admin, category["id"], variants=[_variant("TAKEN-1")])
    error = _error(
        await api_client.post(
            f"{API}/admin/products", json={**base, "variants": [_variant("taken-1")]}, headers=admin
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert error["details"][0]["field"] == "variants.0.sku"


async def test_product_update_list_and_soft_delete(
    api_client: httpx.AsyncClient, admin: dict
) -> None:
    pizza = await _category(api_client, admin, "Пицца")
    drinks = await _category(api_client, admin, "Напитки")
    product = await _product(api_client, admin, pizza["id"])
    response = await api_client.patch(
        f"{API}/admin/products/{product['id']}",
        json={"is_available": False, "category_id": drinks["id"], "sort_order": 3},
        headers=admin,
    )
    assert response.status_code == 200
    assert response.json()["category_id"] == drinks["id"]
    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    assert public["is_available"] is False and public["category_id"] == drinks["id"]

    found = (
        await api_client.get(f"{API}/admin/products", params={"search": "марг"}, headers=admin)
    ).json()
    assert [p["id"] for p in found["items"]] == [product["id"]]
    assert found["items"][0]["name"] == "Маргарита"

    assert (
        await api_client.delete(f"{API}/admin/products/{product['id']}", headers=admin)
    ).status_code == 204
    assert (await api_client.get(f"{API}/catalog/products/{product['id']}")).status_code == 404
    active = (await api_client.get(f"{API}/admin/products", headers=admin)).json()
    deleted = (
        await api_client.get(f"{API}/admin/products", params={"status": "deleted"}, headers=admin)
    ).json()
    assert product["id"] not in {p["id"] for p in active["items"]}
    assert [p["id"] for p in deleted["items"]] == [product["id"]]
    assert deleted["items"][0]["deleted_at"] is not None
    detail = (await api_client.get(f"{API}/admin/products/{product['id']}", headers=admin)).json()
    assert detail["deleted_at"] is not None


async def test_variants_add_and_update(api_client: httpx.AsyncClient, admin: dict) -> None:
    category = await _category(api_client, admin)
    product = await _product(api_client, admin, category["id"])
    added = await api_client.post(
        f"{API}/admin/products/{product['id']}/variants",
        json={**_variant("BIG-40", price="750.00", name="40 см"), "sort_order": 1},
        headers=admin,
    )
    assert added.status_code == 201
    assert len(added.json()["variants"]) == 2
    first_id = product["variants"][0]["id"]
    updated = await api_client.patch(
        f"{API}/admin/variants/{first_id}",
        json={"price": "500.50", "is_available": False},
        headers=admin,
    )
    assert updated.status_code == 200
    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    assert public["price_from"] == "750.00"  # the cheaper size is unavailable now
    assert [(v["name"], v["price"], v["is_available"]) for v in public["variants"]] == [
        ("30 см", "500.50", False),
        ("40 см", "750.00", True),
    ]
    _error(
        await api_client.patch(
            f"{API}/admin/variants/{first_id}", json={"sku": "BIG-40"}, headers=admin
        ),
        422,
        "VALIDATION_ERROR",
    )


# --------------------------------------------------------------------------
# Modifier groups, modifiers, links and per-size prices
# --------------------------------------------------------------------------


async def _group(client: httpx.AsyncClient, admin: dict, **body) -> httpx.Response:
    return await client.post(
        f"{API}/admin/modifier-groups",
        json={"translations": [{"language_code": "ru", "name": body.pop("name", "Тесто")}], **body},
        headers=admin,
    )


async def test_group_rules_dec_128(api_client: httpx.AsyncClient, admin: dict) -> None:
    dough = await _group(
        api_client, admin, selection_type="single", min_selections=1, max_selections=1
    )
    assert dough.status_code == 201
    assert dough.json()["is_required"] is True  # derived from min >= 1
    sauce = await _group(api_client, admin, name="Соус", selection_type="single", max_selections=1)
    assert sauce.json()["is_required"] is False
    for body in (
        {"selection_type": "single"},  # single without max = 1 (DEC-128)
        {"selection_type": "single", "max_selections": 2},
        {"selection_type": "multiple", "min_selections": 3, "max_selections": 2},
    ):
        _error(await _group(api_client, admin, **body), 422, "VALIDATION_ERROR")

    extras = (
        await _group(api_client, admin, name="Добавки", selection_type="multiple", max_selections=3)
    ).json()
    response = await api_client.patch(
        f"{API}/admin/modifier-groups/{extras['id']}",
        json={"clear_max_selections": True},
        headers=admin,
    )
    assert response.json()["max_selections"] is None
    _error(
        await api_client.patch(
            f"{API}/admin/modifier-groups/{extras['id']}",
            json={"selection_type": "single"},
            headers=admin,
        ),
        422,
        "VALIDATION_ERROR",
    )


async def test_full_pizza_setup_reaches_public_catalog(
    api_client: httpx.AsyncClient, admin: dict
) -> None:
    category = await _category(api_client, admin)
    product = await _product(api_client, admin, category["id"])
    big = (
        await api_client.post(
            f"{API}/admin/products/{product['id']}/variants",
            json=_variant("M-40", price="750.00", name="40 см"),
            headers=admin,
        )
    ).json()["variants"][1]
    dough = (
        await _group(api_client, admin, selection_type="single", min_selections=1, max_selections=1)
    ).json()
    extras = (
        await _group(api_client, admin, name="Добавки", selection_type="multiple", max_selections=3)
    ).json()

    thin = await api_client.post(
        f"{API}/admin/modifiers",
        json={"group_id": dough["id"], "translations": [{"language_code": "ru", "name": "Тонкое"}]},
        headers=admin,
    )
    cheese = await api_client.post(
        f"{API}/admin/modifiers",
        json={
            "group_id": extras["id"],
            "price_delta": "60.00",
            "max_quantity": 2,
            "translations": [{"language_code": "ru", "name": "Сыр"}],
        },
        headers=admin,
    )
    assert thin.status_code == 201 and cheese.status_code == 201
    cheese_id = cheese.json()["id"]

    # A per-size price needs the group linked to the product (§5.6).
    _error(
        await api_client.put(
            f"{API}/admin/variants/{big['id']}/modifier-prices",
            json=[{"modifier_id": cheese_id, "price_delta": "80.00"}],
            headers=admin,
        ),
        422,
        "VALIDATION_ERROR",
    )
    linked = await api_client.put(
        f"{API}/admin/products/{product['id']}/modifier-groups",
        json=[
            {"group_id": dough["id"], "sort_order": 0},
            {"group_id": extras["id"], "sort_order": 1},
        ],
        headers=admin,
    )
    assert [g["group_id"] for g in linked.json()["modifier_groups"]] == [dough["id"], extras["id"]]
    priced = await api_client.put(
        f"{API}/admin/variants/{big['id']}/modifier-prices",
        json=[{"modifier_id": cheese_id, "price_delta": "80.00"}],
        headers=admin,
    )
    assert priced.status_code == 200

    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    groups = {g["name"]: g for g in public["modifier_groups"]}
    assert groups["Тесто"]["selection_type"] == "single" and groups["Тесто"]["is_required"] is True
    cheese_public = groups["Добавки"]["modifiers"][0]
    assert cheese_public["max_quantity"] == 2
    assert cheese_public["variant_prices"] == [{"variant_id": big["id"], "price_delta": "80.00"}]

    # Unavailable modifier and inactive group are reflected publicly.
    await api_client.patch(
        f"{API}/admin/modifiers/{cheese_id}", json={"is_available": False}, headers=admin
    )
    await api_client.patch(
        f"{API}/admin/modifier-groups/{dough['id']}", json={"is_active": False}, headers=admin
    )
    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    assert [g["name"] for g in public["modifier_groups"]] == ["Добавки"]
    assert public["modifier_groups"][0]["modifiers"][0]["is_available"] is False

    # Unlinking the extras group removes its per-size prices for this product.
    await api_client.put(
        f"{API}/admin/products/{product['id']}/modifier-groups",
        json=[{"group_id": dough["id"], "sort_order": 0}],
        headers=admin,
    )
    detail = (await api_client.get(f"{API}/admin/products/{product['id']}", headers=admin)).json()
    assert all(v["modifier_prices"] == [] for v in detail["variants"])
    groups_list = (await api_client.get(f"{API}/admin/modifier-groups", headers=admin)).json()[
        "items"
    ]
    assert {g["id"]: g["products_count"] for g in groups_list}[dough["id"]] == 1


async def test_admin_edits_seeded_demo_pizza(
    api_client: httpx.AsyncClient, base: AsyncConnection, admin: dict
) -> None:
    await seed_demo(base)
    products = (
        await api_client.get(f"{API}/admin/products", params={"search": "Маргарита"}, headers=admin)
    ).json()
    product_id = products["items"][0]["id"]
    detail = (await api_client.get(f"{API}/admin/products/{product_id}", headers=admin)).json()
    assert len(detail["variants"]) == 2 and len(detail["modifier_groups"]) == 2
    small = detail["variants"][0]
    await api_client.patch(
        f"{API}/admin/variants/{small['id']}", json={"price": "590.00"}, headers=admin
    )
    public = (await api_client.get(f"{API}/catalog/products/{product_id}")).json()
    assert public["price_from"] == "590.00"


# --------------------------------------------------------------------------
# Images (DEC-70)
# --------------------------------------------------------------------------


def _file(data: bytes, name: str = "photo.png", content_type: str = "image/png") -> dict:
    return {"file": (name, data, content_type)}


async def test_product_images_upload_serve_and_delete(
    api_client: httpx.AsyncClient, admin: dict
) -> None:
    category = await _category(api_client, admin)
    product = await _product(api_client, admin, category["id"])
    first = await api_client.post(
        f"{API}/admin/products/{product['id']}/images",
        files=_file(_png(), name="../../evil name.png"),
        data={"alt_text": "Маргарита"},
        headers=admin,
    )
    assert first.status_code == 201, first.text
    image = first.json()["images"][0]
    assert image["is_primary"] is True  # the first image becomes primary
    assert image["url"].startswith("/media/products/") and image["url"].endswith(".png")
    assert "evil" not in image["url"]  # the server names the file
    stored = Path(os.environ["MEDIA_ROOT"]) / image["url"].removeprefix("/media/")
    assert stored.is_file()

    served = await api_client.get(image["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"

    second = await api_client.post(
        f"{API}/admin/products/{product['id']}/images",
        files=_file(_png(fmt="JPEG"), name="b.jpg", content_type="image/jpeg"),
        data={"is_primary": "true"},
        headers=admin,
    )
    images = second.json()["images"]
    assert [img["is_primary"] for img in images] == [True, False]
    assert images[0]["url"].endswith(".jpg")
    public = (await api_client.get(f"{API}/catalog/products/{product['id']}")).json()
    assert public["image_url"] == images[0]["url"]

    deleted = await api_client.delete(
        f"{API}/admin/products/{product['id']}/images/{image['id']}", headers=admin
    )
    assert deleted.status_code == 204
    assert not stored.exists()


@pytest.mark.parametrize(
    ("data", "name", "content_type"),
    [
        pytest.param(b"not an image at all", "fake.png", "image/png", id="fake-content"),
        pytest.param(_png(), "photo.gif", "image/png", id="wrong-extension"),
        pytest.param(_png(), "photo.png", "image/gif", id="wrong-mime"),
        pytest.param(_png(fmt="GIF"), "photo.gif", "image/gif", id="gif"),
        pytest.param(b"", "empty.png", "image/png", id="empty"),
    ],
)
async def test_invalid_images_are_rejected(
    api_client: httpx.AsyncClient, admin: dict, data: bytes, name: str, content_type: str
) -> None:
    category = await _category(api_client, admin)
    product = await _product(api_client, admin, category["id"])
    response = await api_client.post(
        f"{API}/admin/products/{product['id']}/images",
        files=_file(data, name=name, content_type=content_type),
        headers=admin,
    )
    _error(response, 422, "INVALID_FILE")


async def test_image_size_limit(
    api_client: httpx.AsyncClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    category = await _category(api_client, admin)
    monkeypatch.setenv("IMAGE_MAX_BYTES", "100")
    get_settings.cache_clear()
    try:
        response = await api_client.post(
            f"{API}/admin/categories/{category['id']}/image",
            files=_file(_png(64, 64)),
            headers=admin,
        )
    finally:
        monkeypatch.delenv("IMAGE_MAX_BYTES")
        get_settings.cache_clear()
    _error(response, 422, "INVALID_FILE")


async def test_category_image(api_client: httpx.AsyncClient, admin: dict) -> None:
    category = await _category(api_client, admin)
    response = await api_client.post(
        f"{API}/admin/categories/{category['id']}/image", files=_file(_png()), headers=admin
    )
    assert response.status_code == 200
    url = response.json()["image_url"]
    assert url.startswith("/media/categories/")
    public = (await api_client.get(f"{API}/catalog/categories")).json()["items"]
    assert next(c for c in public if c["id"] == category["id"])["image_url"] == url
