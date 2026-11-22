"""Shared helpers for `/auth` API tests (S3-B).

Cookies are passed explicitly: the client's cookie jar is cleared before
and after every call, so a test always knows exactly which refresh token a
request carries.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ORIGIN = "http://test"  # CSRF_TRUSTED_ORIGINS in tests (conftest.py)
AUTH = "/api/v1/auth"
PASSWORD = "correct1horse"  # noqa: S105 - test data
NEW_PASSWORD = "battery2staple"  # noqa: S105 - test data
CSRF_HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


@dataclass
class SetCookie:
    name: str
    value: str
    attributes: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)


def refresh_set_cookie(response: httpx.Response) -> SetCookie | None:
    """Parse the `refresh_token` Set-Cookie header of a response, if any."""
    for header in response.headers.get_list("set-cookie"):
        parts = [part.strip() for part in header.split(";")]
        name, _, value = parts[0].partition("=")
        if name != "refresh_token":
            continue
        cookie = SetCookie(name=name, value=value.strip('"'))
        for part in parts[1:]:
            key, sep, val = part.partition("=")
            if sep:
                cookie.attributes[key.lower()] = val
            else:
                cookie.flags.add(key.lower())
        return cookie
    return None


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: Any = None,
    refresh: str | None = None,
    access: str | None = None,
    csrf: bool = False,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request_headers: dict[str, str] = dict(CSRF_HEADERS) if csrf else {}
    if refresh is not None:
        request_headers["Cookie"] = f"refresh_token={refresh}"
    if access is not None:
        request_headers["Authorization"] = f"Bearer {access}"
    request_headers.update(headers or {})
    client.cookies.clear()
    try:
        return await client.request(method, f"{AUTH}{path}", json=json, headers=request_headers)
    finally:
        client.cookies.clear()


def register_body(email: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"email": email, "password": PASSWORD, "full_name": "Test User"}
    body.update(overrides)
    return body


@dataclass
class Session:
    access: str
    refresh: str


async def register(client: httpx.AsyncClient, email: str, **overrides: Any) -> Session:
    response = await call(client, "POST", "/register", json=register_body(email, **overrides))
    assert response.status_code == 201, response.text
    cookie = refresh_set_cookie(response)
    assert cookie is not None
    return Session(access=response.json()["access_token"], refresh=cookie.value)


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> Session:
    response = await call(client, "POST", "/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    cookie = refresh_set_cookie(response)
    assert cookie is not None
    return Session(access=response.json()["access_token"], refresh=cookie.value)


async def wait_for_lock_waiters(engine: AsyncEngine, count: int, limit_s: float = 10) -> None:
    """Wait until at least `count` backends of this database wait for a lock."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_s
    while True:
        async with engine.connect() as conn:
            waiting = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        if (waiting or 0) >= count:
            return
        if loop.time() > deadline:
            raise AssertionError(f"expected {count} backends waiting for a lock, got {waiting}")
        await asyncio.sleep(0.02)
