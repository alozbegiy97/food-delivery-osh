"""Rate limits (DEC-80, DEC-95, DEC-108; package S3-C).

Each test builds its own application with limits enabled and small values,
so counters never leak between tests.
"""

import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import create_app

API = "/api/v1"


@pytest.fixture
def limited_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "2/minute")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC", "3/minute")
    monkeypatch.setenv("RATE_LIMIT_AUTHENTICATED", "4/minute")
    monkeypatch.setenv("RATE_LIMIT_PASSWORD_FORGOT", "1/hour")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


@pytest.fixture
async def client(limited_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=limited_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def _assert_429(response: httpx.Response) -> None:
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) >= 1
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


async def test_public_limit_per_ip(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        assert (await client.get(f"{API}/does-not-exist")).status_code == 404
    _assert_429(await client.get(f"{API}/does-not-exist"))


async def test_authenticated_limit_is_per_user(client: httpx.AsyncClient) -> None:
    alice = {"Authorization": f"Bearer {create_access_token(uuid.uuid4()).token}"}
    bob = {"Authorization": f"Bearer {create_access_token(uuid.uuid4()).token}"}
    for _ in range(4):
        assert (await client.get(f"{API}/does-not-exist", headers=alice)).status_code == 404
    _assert_429(await client.get(f"{API}/does-not-exist", headers=alice))
    # Another user and anonymous requests have their own counters.
    assert (await client.get(f"{API}/does-not-exist", headers=bob)).status_code == 404
    assert (await client.get(f"{API}/does-not-exist")).status_code == 404


async def test_invalid_token_counts_as_public(client: httpx.AsyncClient) -> None:
    broken = {"Authorization": "Bearer broken"}
    for _ in range(3):
        await client.get(f"{API}/does-not-exist", headers=broken)
    _assert_429(await client.get(f"{API}/does-not-exist"))


async def test_login_limit(client: httpx.AsyncClient) -> None:
    body = {"email": "x@example.com"}  # invalid body: rejected after the limit check
    for _ in range(2):
        assert (await client.post(f"{API}/auth/login", json=body)).status_code == 422
    _assert_429(await client.post(f"{API}/auth/login", json=body))


async def test_forgot_never_answers_429(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import auth as auth_router

    calls: list[str] = []

    async def fake_request_reset(session, email):  # noqa: ANN001, ANN202
        calls.append(email)

    monkeypatch.setattr(auth_router.password_reset, "request_reset", fake_request_reset)
    responses = [
        await client.post(f"{API}/auth/password/forgot", json={"email": "a@example.com"})
        for _ in range(5)
    ]
    assert {r.status_code for r in responses} == {202}
    assert len({r.text for r in responses}) == 1
    assert calls == ["a@example.com"]  # only the first one inside the 1/hour limit


async def test_limits_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC", "1/minute")
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            assert (await client.get(f"{API}/does-not-exist")).status_code == 404
    get_settings.cache_clear()


# --------------------------------------------------------------------------
# Telegram Mini App (DEC-152 п. 4, DEC-154 п. 6)
# --------------------------------------------------------------------------
#
# Bodies carry an invalid initData, so every request is refused with 401
# before any database access: these tests need no database. The public limit
# is high, so a 429 can only come from the endpoint counters.


@pytest.fixture
async def telegram_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "2/minute")
    monkeypatch.setenv("RATE_LIMIT_TELEGRAM_WEBAPP", "2/minute")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC", "100/minute")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:TEST-unit-token-not-a-real-bot")
    get_settings.cache_clear()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    get_settings.cache_clear()


_BAD = {"init_data": "auth_date=1&user=%7B%7D&hash=" + "0" * 64}
_BAD_LINK = {**_BAD, "email": "x@example.com", "password": "secret1pass"}


async def test_webapp_and_register_share_one_counter(telegram_client: httpx.AsyncClient) -> None:
    webapp = f"{API}/auth/telegram/webapp"
    assert (await telegram_client.post(webapp, json=_BAD)).status_code == 401
    assert (await telegram_client.post(f"{webapp}/register", json=_BAD)).status_code == 401
    _assert_429(await telegram_client.post(webapp, json=_BAD))
    _assert_429(await telegram_client.post(f"{webapp}/register", json=_BAD))
    # Separate from the login counter: /auth/login and /link still pass it.
    assert (await telegram_client.post(f"{API}/auth/login", json={})).status_code == 422
    assert (await telegram_client.post(f"{webapp}/link", json=_BAD_LINK)).status_code == 401


async def test_link_shares_the_login_counter(telegram_client: httpx.AsyncClient) -> None:
    link = f"{API}/auth/telegram/webapp/link"
    assert (await telegram_client.post(link, json=_BAD_LINK)).status_code == 401
    assert (await telegram_client.post(f"{API}/auth/login", json={})).status_code == 422
    _assert_429(await telegram_client.post(link, json=_BAD_LINK))
    _assert_429(await telegram_client.post(f"{API}/auth/login", json={}))
    # The Mini App login counter is untouched.
    webapp = f"{API}/auth/telegram/webapp"
    assert (await telegram_client.post(webapp, json=_BAD)).status_code == 401


async def test_invalid_bodies_spend_the_telegram_counter(
    telegram_client: httpx.AsyncClient,
) -> None:
    webapp = f"{API}/auth/telegram/webapp"
    assert (await telegram_client.post(webapp, json={})).status_code == 422
    assert (await telegram_client.post(webapp, json={"init_data": 1})).status_code == 422
    _assert_429(await telegram_client.post(webapp, json=_BAD))
