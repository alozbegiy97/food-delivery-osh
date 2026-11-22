"""Shared fixtures of the stage 6 tests (checkout, orders, addresses).

Everything runs inside the rolled-back transaction of `api_client`; the
demo catalog, zone (Osh, fee 100, minimum 500), restaurant settings
(minimum 300, 10:00–23:00 Asia/Bishkek) come from the seeds (DEC-118,
DEC-119, DEC-124). The clock of the checkout calculation is fixed so the
working-hours checks do not depend on when the tests run.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import create_access_token, hash_password
from app.modules.catalog.models import Product, ProductVariant
from app.modules.orders import checkout
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole
from app.seeds.base import seed_base
from app.seeds.demo import seed_demo

API = "/api/v1"
# Wednesday 2026-11-11: 12:00 and 02:00 (next night) in Asia/Bishkek (UTC+6).
OPEN_AT = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)
CLOSED_AT = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)
# Inside / outside the demo zone (lon 72.74–72.86, lat 40.49–40.57).
INSIDE = {"latitude": "40.5300000", "longitude": "72.8000000"}
OUTSIDE = {"latitude": "40.6500000", "longitude": "72.8000000"}


async def make_user(
    conn: AsyncConnection, *roles: str, language: str = "ru", phone: str | None = None
) -> dict[str, str]:
    role_ids = dict((await conn.execute(select(Role.name, Role.id))).all())
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=f"{uuid.uuid4().hex}@example.com",
            password_hash=hash_password("correct1horse"),
            full_name="Покупатель",
            phone=phone,
            preferred_language=language,
        )
        .returning(User.id)
    )
    for role in roles:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_ids[role]))
    return {"Authorization": f"Bearer {create_access_token(user_id).token}"}


def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert body["code"] == code, body
    return body


class Clock:
    def __init__(self) -> None:
        self.now = OPEN_AT

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    value = Clock()
    monkeypatch.setattr(checkout, "utc_now", value)
    yield value


@pytest.fixture
async def demo(api_conn: AsyncConnection) -> AsyncConnection:
    await seed_base(api_conn)
    await seed_demo(api_conn)
    return api_conn


@pytest.fixture
async def customer(demo: AsyncConnection) -> dict[str, str]:
    return await make_user(demo, RoleName.CUSTOMER.value)


async def variant_of(conn: AsyncConnection, slug: str, index: int = 0) -> tuple[str, str, Decimal]:
    """(product_id, variant_id, price) of a demo product, variants by price."""
    rows = (
        await conn.execute(
            select(Product.id, ProductVariant.id, ProductVariant.price)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .where(Product.slug == slug)
            .order_by(ProductVariant.price)
        )
    ).all()
    product_id, variant_id, price = rows[index]
    return str(product_id), str(variant_id), price


async def add_kompot(
    client: httpx.AsyncClient, conn: AsyncConnection, headers: dict, quantity: int, big: bool = True
) -> Decimal:
    """Add kompot (no extras) to the cart; returns the line total."""
    product_id, variant_id, price = await variant_of(conn, "demo-drink-kompot", 1 if big else 0)
    ok(
        await client.post(
            f"{API}/cart/items",
            json={"product_id": product_id, "variant_id": variant_id, "quantity": quantity},
            headers=headers,
        )
    )
    return price * quantity


def order_body(total: str, **extra: object) -> dict:
    body: dict = {
        "delivery_type": "pickup",
        "customer_name": "Айбек",
        "customer_phone": "0700 12 34 56",
        "payment_method_code": "cash",
        "expected_total": total,
    }
    body.update(extra)
    return body


def delivery_body(total: str, point: dict | None = None, **extra: object) -> dict:
    return order_body(
        total,
        delivery_type="delivery",
        address={"address_text": "ул. Ленина, 1", **(point or INSIDE), **extra.pop("address", {})},
        **extra,
    )


def key() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}
