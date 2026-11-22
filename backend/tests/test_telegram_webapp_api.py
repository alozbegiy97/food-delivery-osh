"""`/auth/telegram/webapp*` through HTTP (API §2.3; DEC-152, DEC-154, U1, U2, D5).

Each request runs inside the test's rolled-back transaction (api_client),
so every test also checks the database before and after. Real COMMITs,
locks and concurrency are covered by test_telegram_webapp_concurrency.py;
rate limits by test_rate_limit.py.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.security import decode_access_token, hash_password
from app.modules.notifications.models import TelegramLink
from app.modules.users.enums import RoleName
from app.modules.users.models import Address, RefreshToken, Role, User, UserRole
from tests.auth_http import NEW_PASSWORD, PASSWORD, call, login
from tests.telegram_init_data import OTHER_BOT_TOKEN, TEST_BOT_TOKEN, init_data

pytestmark = pytest.mark.db

WEBAPP = "/api/v1/auth/telegram/webapp"
TG_ID = 279058397
OTHER_TG_ID = 512345678
SITE_EMAIL = "site@example.com"


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture
def telegram_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A throw-away bot token for this test only."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def roles(api_conn: AsyncConnection) -> dict[str, uuid.UUID]:
    rows = await api_conn.execute(
        insert(Role)
        .values([{"name": name.value} for name in RoleName])
        .returning(Role.name, Role.id)
    )
    return {name: role_id for name, role_id in rows.all()}


async def post(client: httpx.AsyncClient, path: str, body: Any) -> httpx.Response:
    client.cookies.clear()
    try:
        return await client.post(f"{WEBAPP}{path}", json=body)
    finally:
        client.cookies.clear()


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


def assert_token(response: httpx.Response, user_id: uuid.UUID) -> str:
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"  # noqa: S105 - OAuth token type
    assert body["expires_in"] == 15 * 60
    assert "set-cookie" not in response.headers  # no refresh cookie (DEC-142)
    assert decode_access_token(body["access_token"]) == user_id
    return body["access_token"]


async def add_user(
    conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    email: str | None = SITE_EMAIL,
    *,
    role_names: tuple[str, ...] = ("customer",),
    password_hash: str | None = None,
    **values: Any,
) -> uuid.UUID:
    defaults: dict[str, Any] = {
        "full_name": "Сайт Клиент",
        "phone": "+996700123456",
        "preferred_language": "ky",
    }
    defaults.update(values)
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=email,
            password_hash=(password_hash or hash_password(PASSWORD)) if email else None,
            **defaults,
        )
        .returning(User.id)
    )
    for name in role_names:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=roles[name]))
    return user_id


async def add_link(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    chat_id: int = TG_ID,
    *,
    is_active: bool = True,
    username: str | None = "old_name",
) -> datetime:
    linked_at = datetime.now(UTC) - timedelta(days=3)
    await conn.execute(
        insert(TelegramLink).values(
            user_id=user_id,
            telegram_chat_id=chat_id,
            telegram_username=username,
            is_active=is_active,
            linked_at=linked_at,
        )
    )
    return linked_at


async def links(conn: AsyncConnection) -> list[tuple]:
    rows = await conn.execute(
        select(
            TelegramLink.user_id,
            TelegramLink.telegram_chat_id,
            TelegramLink.telegram_username,
            TelegramLink.is_active,
            TelegramLink.linked_at,
        ).order_by(TelegramLink.telegram_chat_id)
    )
    return [tuple(row) for row in rows.all()]


async def counts(conn: AsyncConnection) -> dict[str, int]:
    return {
        model.__tablename__: int(await conn.scalar(select(func.count()).select_from(model)) or 0)
        for model in (User, UserRole, TelegramLink, RefreshToken)
    }


async def user_row(conn: AsyncConnection, user_id: uuid.UUID) -> tuple:
    row = (
        await conn.execute(
            select(
                User.email,
                User.password_hash,
                User.full_name,
                User.phone,
                User.preferred_language,
                User.is_active,
                User.must_change_password,
                User.updated_at,
            ).where(User.id == user_id)
        )
    ).one()
    return tuple(row)


async def role_names(conn: AsyncConnection, user_id: uuid.UUID) -> set[str]:
    rows = await conn.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return set(rows.all())


def body(**kwargs: Any) -> dict[str, str]:
    return {"init_data": init_data(**kwargs)}


def link_body(email: str = SITE_EMAIL, password: str = PASSWORD, **kwargs: Any) -> dict[str, str]:
    return {"init_data": init_data(**kwargs), "email": email, "password": password}


# --------------------------------------------------------------------------
# Configuration and request validation (all three endpoints)
# --------------------------------------------------------------------------

PATHS = ["", "/register", "/link"]


def _valid_body(path: str) -> dict[str, str]:
    return link_body() if path == "/link" else body()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("token", [None, "", "   "])
async def test_disabled_without_bot_token(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    token: str | None,
) -> None:
    if token is None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    get_settings.cache_clear()
    try:
        await add_user(api_conn, roles)
        before = await counts(api_conn)
        assert_error(await post(api_client, path, _valid_body(path)), 409, "TELEGRAM_DISABLED")
        assert await counts(api_conn) == before
    finally:
        get_settings.cache_clear()


def _bad_init_data() -> dict[str, str]:
    now = int(datetime.now(UTC).timestamp())
    good = init_data()
    return {
        "other_bot": init_data(bot_token=OTHER_BOT_TOKEN),
        "tampered": good.replace("Test", "Tset"),
        "expired": init_data(auth_date=now - 3601),
        "future": init_data(auth_date=now + 120),
        "bot": init_data(is_bot=True),
        "empty": "",
        "garbage": "not init data",
        # D5: over the limit is 401, never 422 (4097 and far beyond).
        "length_4097": init_data(extra={"pad": "x" * 4200})[:4097],
        "huge": "a=" + "x" * 100_000,
    }


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("case", list(_bad_init_data()))
async def test_invalid_init_data_is_401_everywhere(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    path: str,
    case: str,
) -> None:
    user_id = await add_user(api_conn, roles)
    await add_link(api_conn, user_id)
    before = (await counts(api_conn), await links(api_conn))
    raw = _bad_init_data()[case]
    request = {"init_data": raw}
    if path == "/link":
        request |= {"email": SITE_EMAIL, "password": PASSWORD}  # right password
    response = await post(api_client, path, request)
    error = assert_error(response, 401, "INVALID_TELEGRAM_AUTH")
    assert error["details"] == []
    assert raw[:40] not in response.text if raw else True
    assert (await counts(api_conn), await links(api_conn)) == before


async def test_init_data_of_exactly_4096_characters_is_accepted(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles)
    await add_link(api_conn, user_id)
    base = init_data(extra={"pad": ""})
    raw = init_data(extra={"pad": "x" * (4096 - len(base))})
    assert len(raw) == 4096
    assert_token(await post(api_client, "", {"init_data": raw}), user_id)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: {**b, "init_data": 123},
        lambda b: {k: v for k, v in b.items() if k != "init_data"},
        lambda b: {**b, "user_id": str(uuid.uuid4())},
        lambda b: {**b, "role": "admin"},
        lambda b: [],
    ],
)
async def test_schema_errors_are_422_without_input(
    api_client: httpx.AsyncClient, telegram_on: None, path: str, mutate: Any
) -> None:
    request = mutate(_valid_body(path))
    response = await post(api_client, path, request)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert PASSWORD not in response.text
    assert "auth_date" not in response.text and "query_id" not in response.text


@pytest.mark.parametrize(
    "request_body",
    [
        {"init_data": "x", "email": "", "password": PASSWORD},
        {"init_data": "x", "email": SITE_EMAIL, "password": ""},
        {"init_data": "x", "email": SITE_EMAIL},
        {"init_data": "x", "email": SITE_EMAIL, "password": "p" * 1025},
    ],
)
async def test_link_credentials_schema(
    api_client: httpx.AsyncClient, telegram_on: None, request_body: dict[str, str]
) -> None:
    response = await post(api_client, "/link", request_body)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert PASSWORD not in response.text and "p" * 50 not in response.text


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp (login only)
# --------------------------------------------------------------------------


async def test_login_without_link_is_409_and_creates_nothing(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    await add_user(api_conn, roles)
    before = await counts(api_conn)
    assert_error(await post(api_client, "", body()), 409, "TELEGRAM_NOT_LINKED")
    assert await counts(api_conn) == before


async def test_login_of_linked_customer(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles)
    await add_link(api_conn, user_id)
    profile = await user_row(api_conn, user_id)
    token = assert_token(await post(api_client, "", body()), user_id)

    me = await call(api_client, "GET", "/me", access=token)
    assert me.status_code == 200
    assert me.json()["email"] == SITE_EMAIL
    assert me.json()["roles"] == ["customer"]
    assert await user_row(api_conn, user_id) == profile


async def test_login_of_inactive_user_is_401(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles, is_active=False)
    await add_link(api_conn, user_id, is_active=False)
    before = await links(api_conn)
    assert_error(
        await post(api_client, "", body(allows_write_to_pm=True)), 401, "INVALID_TELEGRAM_AUTH"
    )
    assert await links(api_conn) == before  # not even is_active is raised


@pytest.mark.parametrize("staff_role", ["cook", "courier", "admin"])
async def test_login_of_staff_is_403(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    staff_role: str,
) -> None:
    user_id = await add_user(api_conn, roles, role_names=(staff_role,))
    await add_link(api_conn, user_id)
    assert_error(await post(api_client, "", body()), 403, "FORBIDDEN")


@pytest.mark.parametrize(
    ("stored", "user_fields", "expected"),
    [
        (False, {"allows_write_to_pm": True}, True),
        (False, {"allows_write_to_pm": False}, False),
        (False, {}, False),  # missing = false (DEC-154 п. 3)
        (True, {"allows_write_to_pm": False}, True),  # never lowered
        (True, {}, True),
        (True, {"allows_write_to_pm": True}, True),
    ],
)
async def test_login_raises_is_active_only_to_true(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    stored: bool,
    user_fields: dict[str, Any],
    expected: bool,
) -> None:
    user_id = await add_user(api_conn, roles)
    linked_at = await add_link(api_conn, user_id, is_active=stored)
    response = await post(api_client, "", body(username="new_name", **user_fields))
    assert_token(response, user_id)
    # username and linked_at are never updated by a login (DEC-154 п. 4).
    assert await links(api_conn) == [(user_id, TG_ID, "old_name", expected, linked_at)]


async def test_login_ignores_link_is_active_for_authentication(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    """is_active is the bot's write permission, not the existence of the link."""
    user_id = await add_user(api_conn, roles)
    await add_link(api_conn, user_id, is_active=False)
    assert_token(await post(api_client, "", body(allows_write_to_pm=False)), user_id)


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp/register
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_fields", "is_active"),
    [({"allows_write_to_pm": True}, True), ({"allows_write_to_pm": False}, False), ({}, False)],
)
async def test_register_creates_a_telegram_only_customer(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    user_fields: dict[str, Any],
    is_active: bool,
) -> None:
    before = await counts(api_conn)
    response = await post(
        api_client,
        "/register",
        body(
            first_name="Айбек",
            last_name="Осмонов",
            username="aibek",
            language_code="ky",
            **user_fields,
        ),
    )
    assert response.status_code == 200, response.text
    user_id = decode_access_token(response.json()["access_token"])
    assert "set-cookie" not in response.headers

    email, password_hash, full_name, phone, language, active, must_change, _ = await user_row(
        api_conn, user_id
    )
    assert (email, password_hash, phone) == (None, None, None)
    assert (full_name, language, active, must_change) == ("Айбек Осмонов", "ky", True, False)
    assert await role_names(api_conn, user_id) == {"customer"}
    [(link_user, chat_id, username, link_active, _)] = await links(api_conn)
    assert (link_user, chat_id, username, link_active) == (user_id, TG_ID, "aibek", is_active)
    after = await counts(api_conn)
    assert after["users"] == before["users"] + 1
    assert after["user_roles"] == before["user_roles"] + 1
    assert after["telegram_links"] == before["telegram_links"] + 1
    assert after["refresh_tokens"] == before["refresh_tokens"]

    me = (await call(api_client, "GET", "/me", access=response.json()["access_token"])).json()
    assert (me["email"], me["has_password"], me["roles"]) == (None, False, ["customer"])


async def test_register_is_idempotent(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    first = await post(api_client, "/register", body(allows_write_to_pm=False))
    user_id = decode_access_token(first.json()["access_token"])
    after_first = (await counts(api_conn), await links(api_conn))

    again = await post(api_client, "/register", body(first_name="Changed", username="changed"))
    assert_token(again, user_id)
    assert (await counts(api_conn), await links(api_conn)) == after_first
    assert (await user_row(api_conn, user_id))[2] == "Test"  # name not overwritten


async def test_register_with_telegram_linked_to_site_account_logs_into_it(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles)
    linked_at = await add_link(api_conn, user_id, is_active=False)
    profile = await user_row(api_conn, user_id)
    before = await counts(api_conn)

    response = await post(api_client, "/register", body(allows_write_to_pm=True))
    assert_token(response, user_id)
    assert await counts(api_conn) == before  # no second account
    assert await user_row(api_conn, user_id) == profile
    # As a login: is_active raised, username kept (DEC-154 пп. 3, 4).
    assert await links(api_conn) == [(user_id, TG_ID, "old_name", True, linked_at)]


async def test_register_of_linked_inactive_or_staff_account(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    inactive = await add_user(api_conn, roles, is_active=False)
    await add_link(api_conn, inactive)
    cook = await add_user(api_conn, roles, "cook@example.com", role_names=("cook",))
    await add_link(api_conn, cook, OTHER_TG_ID)
    before = await counts(api_conn)
    assert_error(await post(api_client, "/register", body()), 401, "INVALID_TELEGRAM_AUTH")
    assert_error(
        await post(api_client, "/register", body(telegram_id=OTHER_TG_ID)), 403, "FORBIDDEN"
    )
    assert await counts(api_conn) == before


@pytest.mark.parametrize(
    ("user_fields", "expected"),
    [
        ({"first_name": "  Анна ", "last_name": " Ли "}, "Анна   Ли"),
        ({"first_name": "Bad\u0007Name"}, "BadName"),
        ({"first_name": "Ө" * 160}, "Ө" * 150),
        ({"first_name": "a" * 149, "last_name": "Zed"}, "a" * 149),
        ({"first_name": "", "username": "only_user"}, "only_user"),
        ({"first_name": "\u0007\u0008", "username": "ctrl"}, "ctrl"),
        ({"first_name": ""}, "Telegram"),
        ({"first_name": " ", "username": "x" * 101}, "Telegram"),  # U2: username dropped
    ],
)
async def test_register_name_rules(
    api_client: httpx.AsyncClient,
    roles: dict[str, uuid.UUID],
    api_conn: AsyncConnection,
    telegram_on: None,
    user_fields: dict[str, Any],
    expected: str,
) -> None:
    response = await post(api_client, "/register", body(**user_fields))
    user_id = decode_access_token(response.json()["access_token"])
    assert (await user_row(api_conn, user_id))[2] == expected


@pytest.mark.parametrize(
    ("language_code", "expected"),
    [
        ("ru", "ru"),
        ("ky", "ky"),
        ("uz", "uz"),
        ("ru-RU", "ru"),
        ("uz-Latn", "ru"),
        ("en", "ru"),
        ("KY", "ru"),
        (None, "ru"),
    ],
)
async def test_register_language(
    api_client: httpx.AsyncClient,
    roles: dict[str, uuid.UUID],
    api_conn: AsyncConnection,
    telegram_on: None,
    language_code: str | None,
    expected: str,
) -> None:
    fields = {} if language_code is None else {"language_code": language_code}
    response = await post(api_client, "/register", body(**fields))
    user_id = decode_access_token(response.json()["access_token"])
    assert (await user_row(api_conn, user_id))[4] == expected


async def test_register_stores_null_for_a_username_over_100(
    api_client: httpx.AsyncClient,
    roles: dict[str, uuid.UUID],
    api_conn: AsyncConnection,
    telegram_on: None,
) -> None:
    response = await post(api_client, "/register", body(username="u" * 101))
    assert response.status_code == 200
    [(_, _, username, _, _)] = await links(api_conn)
    assert username is None


# --------------------------------------------------------------------------
# POST /auth/telegram/webapp/link
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_fields", "is_active"), [({"allows_write_to_pm": True}, True), ({}, False)]
)
async def test_link_creates_the_link_and_changes_nothing_else(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    user_fields: dict[str, Any],
    is_active: bool,
) -> None:
    user_id = await add_user(api_conn, roles)
    session = await login(api_client, SITE_EMAIL)  # an existing refresh family
    await api_conn.execute(insert(Address).values(user_id=user_id, address_text="ул. Ленина, 1"))
    profile = await user_row(api_conn, user_id)
    tokens_before = await counts(api_conn)

    response = await post(
        api_client,
        "/link",
        link_body(
            email="  SITE@Example.COM ",
            username="tg_user",
            first_name="Other",
            language_code="uz",
            **user_fields,
        ),
    )
    assert_token(response, user_id)
    [(link_user, chat_id, username, link_active, _)] = await links(api_conn)
    assert (link_user, chat_id, username, link_active) == (user_id, TG_ID, "tg_user", is_active)
    # Name, phone, language, email, hash, flags: untouched (no rehash either).
    assert await user_row(api_conn, user_id) == profile
    after = await counts(api_conn)
    assert after["telegram_links"] == tokens_before["telegram_links"] + 1
    assert {k: v for k, v in after.items() if k != "telegram_links"} == {
        k: v for k, v in tokens_before.items() if k != "telegram_links"
    }
    assert await api_conn.scalar(select(func.count()).select_from(Address)) == 1
    # The site session keeps working.
    refreshed = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert refreshed.status_code == 200


async def test_link_never_rehashes_the_password(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    outdated = PasswordHasher(time_cost=2, memory_cost=2048, parallelism=1).hash(PASSWORD)
    user_id = await add_user(api_conn, roles, password_hash=outdated)
    assert_token(await post(api_client, "/link", link_body()), user_id)
    assert (await user_row(api_conn, user_id))[1] == outdated  # /auth/login would rehash


async def test_link_credential_failures_look_the_same(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    await add_user(api_conn, roles)
    await add_user(api_conn, roles, "off@example.com", is_active=False)
    await add_user(api_conn, roles, None, full_name="Telegram only")  # no email
    before = (await counts(api_conn), await links(api_conn))

    cases = [
        link_body(password="wrong1password"),
        link_body(email="nobody@example.com"),
        link_body(email="off@example.com"),
        link_body(email="off@example.com", password="wrong1password"),
    ]
    errors = []
    for request in cases:
        response = await post(api_client, "/link", request)
        errors.append(
            (response.status_code, assert_error(response, 401, "INVALID_CREDENTIALS")["message"])
        )
    assert len(set(errors)) == 1
    assert (await counts(api_conn), await links(api_conn)) == before


async def test_link_checks_init_data_before_the_password(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    await add_user(api_conn, roles)
    for password in (PASSWORD, "wrong1password"):
        response = await post(
            api_client, "/link", link_body(password=password, bot_token=OTHER_BOT_TOKEN)
        )
        assert_error(response, 401, "INVALID_TELEGRAM_AUTH")


@pytest.mark.parametrize("staff_role", ["cook", "courier", "admin"])
async def test_link_of_staff_is_403(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    staff_role: str,
) -> None:
    await add_user(api_conn, roles, role_names=(staff_role,))
    assert_error(await post(api_client, "/link", link_body()), 403, "FORBIDDEN")
    assert await links(api_conn) == []


async def test_link_conflicts_change_nothing(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    site = await add_user(api_conn, roles)
    other = await add_user(api_conn, roles, "other@example.com")
    await add_link(api_conn, other, TG_ID)  # this Telegram belongs to `other`
    before = (await counts(api_conn), await links(api_conn), await user_row(api_conn, site))
    assert_error(await post(api_client, "/link", link_body()), 409, "TELEGRAM_ALREADY_LINKED")

    await add_link(api_conn, site, OTHER_TG_ID)  # `site` has another Telegram
    before = (await counts(api_conn), await links(api_conn), await user_row(api_conn, site))
    fresh_tg = 777000111
    assert_error(
        await post(api_client, "/link", link_body(telegram_id=fresh_tg)),
        409,
        "ACCOUNT_ALREADY_LINKED",
    )
    # Both conflicts at once: TELEGRAM_ALREADY_LINKED first (API §2.3 order).
    assert_error(await post(api_client, "/link", link_body()), 409, "TELEGRAM_ALREADY_LINKED")
    assert (await counts(api_conn), await links(api_conn), await user_row(api_conn, site)) == before


@pytest.mark.parametrize(
    ("stored", "user_fields", "expected"),
    [
        (False, {"allows_write_to_pm": True}, True),
        (True, {"allows_write_to_pm": False}, True),
        (False, {}, False),
    ],
)
async def test_link_of_the_same_pair_is_idempotent(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    stored: bool,
    user_fields: dict[str, Any],
    expected: bool,
) -> None:
    user_id = await add_user(api_conn, roles)
    linked_at = await add_link(api_conn, user_id, is_active=stored)
    profile = await user_row(api_conn, user_id)
    response = await post(api_client, "/link", link_body(username="new_name", **user_fields))
    assert_token(response, user_id)
    assert await links(api_conn) == [(user_id, TG_ID, "old_name", expected, linked_at)]
    assert await user_row(api_conn, user_id) == profile


# --------------------------------------------------------------------------
# Compatibility with MA-1 and the site
# --------------------------------------------------------------------------


async def test_telegram_account_adds_credentials_and_keeps_both_logins(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    registered = await post(api_client, "/register", body(language_code="uz"))
    token = registered.json()["access_token"]
    user_id = decode_access_token(token)

    changed = await call(
        api_client,
        "POST",
        "/password/change",
        access=token,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert_error(changed, 409, "PASSWORD_NOT_SET")

    added = await call(
        api_client,
        "POST",
        "/credentials",
        access=token,
        json={"email": "tg@example.com", "password": PASSWORD},
    )
    assert added.status_code == 204, added.text
    site = await login(api_client, "tg@example.com")
    assert decode_access_token(site.access) == user_id

    # Language changed in the profile is not overwritten by later logins.
    patched = await api_client.patch(
        "/api/v1/users/me",
        json={"preferred_language": "ky"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patched.status_code == 200
    assert_token(await post(api_client, "", body(language_code="ru")), user_id)
    assert (await user_row(api_conn, user_id))[4] == "ky"
    # The same pair linked again by email/password is idempotent.
    assert_token(await post(api_client, "/link", link_body(email="tg@example.com")), user_id)
    assert len(await links(api_conn)) == 1


async def test_site_login_is_unchanged_by_a_link(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles)
    await post(api_client, "/link", link_body())
    site = await login(api_client, SITE_EMAIL)
    assert decode_access_token(site.access) == user_id
    assert site.refresh  # the site still gets its refresh cookie


async def test_deactivated_after_link_cannot_log_in(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
) -> None:
    user_id = await add_user(api_conn, roles)
    token = assert_token(await post(api_client, "/link", link_body()), user_id)
    await api_conn.execute(update(User).where(User.id == user_id).values(is_active=False))
    assert_error(await post(api_client, "", body()), 401, "INVALID_TELEGRAM_AUTH")
    me = await call(api_client, "GET", "/me", access=token)
    assert_error(me, 401, "UNAUTHORIZED")  # existing tokens are checked against the DB


# --------------------------------------------------------------------------
# Nothing sensitive in logs
# --------------------------------------------------------------------------


async def test_secrets_never_reach_the_logs(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    telegram_on: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    await add_user(api_conn, roles)
    secret_password = "Unique9Secret"  # noqa: S105 - test data
    raw = init_data(username="log_probe_user")
    responses = [
        await post(api_client, "/register", {"init_data": raw}),
        await post(api_client, "", {"init_data": raw}),
        await post(
            api_client,
            "/link",
            {"init_data": raw, "email": SITE_EMAIL, "password": secret_password},
        ),
        await post(
            api_client, "/link", {"init_data": raw, "email": SITE_EMAIL, "password": PASSWORD}
        ),
        await post(api_client, "", {"init_data": raw + "x"}),
        await post(
            api_client, "/link", {"init_data": 1, "email": SITE_EMAIL, "password": secret_password}
        ),
    ]
    tokens = [r.json()["access_token"] for r in responses if r.status_code == 200]
    assert tokens
    for needle in (
        raw,
        raw[:60],
        "log_probe_user",
        secret_password,
        PASSWORD,
        TEST_BOT_TOKEN,
        *tokens,
    ):
        assert needle not in caplog.text
    for response in responses:
        assert secret_password not in response.text
        assert TEST_BOT_TOKEN not in response.text
