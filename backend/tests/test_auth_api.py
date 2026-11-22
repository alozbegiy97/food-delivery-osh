"""`/auth` API inside one rolled-back transaction (api_client; S3-B).

DEC-140 (tokens, refresh, logout, CSRF, cookie, password change), DEC-141
(registration fields), DEC-28 (must_change_password), DEC-66 (roles and
is_active from the database). Visibility after real COMMIT, locks,
concurrency and COMMIT failures are in test_auth_commit.py.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import create_access_token, decode_access_token, hash_password
from app.modules.auth.dependencies import CurrentUser, get_current_user, require_roles
from app.modules.auth.refresh_sessions import create_family, hash_refresh_token
from app.modules.users.enums import RoleName
from app.modules.users.models import RefreshToken, Role, User, UserRole
from tests.auth_http import (
    CSRF_HEADERS,
    NEW_PASSWORD,
    ORIGIN,
    PASSWORD,
    call,
    login,
    refresh_set_cookie,
    register,
    register_body,
)

pytestmark = pytest.mark.db

EMAIL = "user@example.com"


@pytest.fixture
async def roles(api_conn: AsyncConnection) -> dict[str, uuid.UUID]:
    """Reference roles inside the test transaction (seed `base` creates them)."""
    rows = await api_conn.execute(
        insert(Role)
        .values([{"name": name.value} for name in RoleName])
        .returning(Role.name, Role.id)
    )
    return {name: role_id for name, role_id in rows.all()}


async def insert_user(
    conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    email: str,
    *,
    role_names: tuple[str, ...] = ("customer",),
    is_active: bool = True,
    must_change_password: bool = False,
    password_hash: str | None = None,
) -> uuid.UUID:
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=email,
            password_hash=password_hash or hash_password(PASSWORD),
            full_name="Staff Or Customer",
            is_active=is_active,
            must_change_password=must_change_password,
        )
        .returning(User.id)
    )
    assert user_id is not None
    for name in role_names:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=roles[name]))
    return user_id


async def tokens_of(conn: AsyncConnection, user_id: uuid.UUID) -> list:
    return list(
        (
            await conn.execute(
                select(
                    RefreshToken.id,
                    RefreshToken.family_id,
                    RefreshToken.token_hash,
                    RefreshToken.revoked_at,
                    RefreshToken.replaced_by_id,
                ).where(RefreshToken.user_id == user_id)
            )
        ).all()
    )


async def user_id_of(conn: AsyncConnection, email: str) -> uuid.UUID:
    user_id = await conn.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return user_id


def assert_error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


# --------------------------------------------------------------------------
# Registration (DEC-141)
# --------------------------------------------------------------------------


async def test_register_creates_customer_session(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    response = await call(
        api_client,
        "POST",
        "/register",
        json=register_body(
            "  New.User@Example.COM ",
            full_name="  Айгуль Ташиева  ",
            phone="0 700 12 34 56",
            preferred_language="ky",
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"  # noqa: S105 - not a secret
    assert body["expires_in"] == 900
    user_id = decode_access_token(body["access_token"])

    row = (
        await api_conn.execute(
            select(
                User.email,
                User.full_name,
                User.phone,
                User.preferred_language,
                User.password_hash,
                User.must_change_password,
            ).where(User.id == user_id)
        )
    ).one()
    assert row.email == "new.user@example.com"
    assert row.full_name == "Айгуль Ташиева"
    assert row.phone == "+996700123456"
    assert row.preferred_language == "ky"
    assert row.password_hash.startswith("$argon2id$")
    assert not row.must_change_password
    role_names = (
        await api_conn.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
    ).all()
    assert role_names == ["customer"]

    cookie = refresh_set_cookie(response)
    assert cookie is not None
    tokens = await tokens_of(api_conn, user_id)
    assert len(tokens) == 1
    assert tokens[0].token_hash == hash_refresh_token(cookie.value)
    assert cookie.value not in tokens[0].token_hash


async def test_refresh_cookie_attributes(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    response = await call(api_client, "POST", "/register", json=register_body(EMAIL))
    cookie = refresh_set_cookie(response)
    assert cookie is not None
    assert cookie.attributes["path"] == "/api/v1/auth"
    assert cookie.attributes["max-age"] == str(30 * 24 * 60 * 60)
    assert cookie.attributes["samesite"].lower() == "strict"
    assert "httponly" in cookie.flags
    assert "secure" not in cookie.flags  # APP_ENV=test (DEC-140)


async def test_refresh_cookie_is_secure_in_demo(
    app: FastAPI,
    api_client: httpx.AsyncClient,
    roles: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("APP_ENV", "demo")
    get_settings.cache_clear()
    try:
        response = await call(api_client, "POST", "/register", json=register_body(EMAIL))
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        get_settings.cache_clear()
    cookie = refresh_set_cookie(response)
    assert cookie is not None
    assert "secure" in cookie.flags


async def test_register_duplicate_email_is_case_insensitive(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    await register(api_client, EMAIL)
    response = await call(api_client, "POST", "/register", json=register_body(" USER@example.COM "))
    assert_error(response, 409, "EMAIL_ALREADY_EXISTS")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"role": "admin"}, id="role-field"),
        pytest.param({"is_active": False}, id="is-active-field"),
        pytest.param({"email": "not-an-email"}, id="bad-email"),
        pytest.param({"email": "a@example.test"}, id="special-use-domain"),
        pytest.param({"email": "a" * 250 + "@x.com"}, id="email-too-long"),
        pytest.param({"password": "short1"}, id="password-too-short"),
        pytest.param({"password": "lettersonly"}, id="password-no-digit"),
        pytest.param({"password": "12345678"}, id="password-no-letter"),
        pytest.param({"password": "a1" * 64 + "x"}, id="password-too-long"),
        pytest.param({"full_name": "   "}, id="name-blank"),
        pytest.param({"full_name": "я" * 151}, id="name-too-long"),
        pytest.param({"full_name": "Bad\x07Name"}, id="name-control-char"),
        pytest.param({"phone": "+7 700 123 45 67"}, id="phone-other-country"),
        pytest.param({"preferred_language": "en"}, id="language"),
    ],
)
async def test_register_rejects_invalid_fields(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID], overrides: dict
) -> None:
    response = await call(
        api_client, "POST", "/register", json={**register_body(EMAIL), **overrides}
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert PASSWORD not in response.text


async def test_register_name_length_counts_unicode_characters(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    name = "ё" * 150  # 150 characters, 300 bytes
    session = await register(api_client, EMAIL, full_name=f"  {name}  ")
    user_id = decode_access_token(session.access)
    assert await api_conn.scalar(select(User.full_name).where(User.id == user_id)) == name


async def test_register_without_customer_role_fails_loudly(
    api_client: httpx.AsyncClient,
) -> None:
    response = await call(api_client, "POST", "/register", json=register_body(EMAIL))
    assert_error(response, 500, "INTERNAL_ERROR")
    assert refresh_set_cookie(response) is None


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


async def test_login_issues_new_family(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    first = await register(api_client, EMAIL)
    second = await login(api_client, " User@Example.com ")
    user_id = decode_access_token(second.access)
    assert user_id == decode_access_token(first.access)
    tokens = await tokens_of(api_conn, user_id)
    assert len({t.family_id for t in tokens}) == 2
    assert all(t.revoked_at is None for t in tokens)


async def test_login_failures_look_the_same(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    await register(api_client, EMAIL)
    await insert_user(api_conn, roles, "inactive@example.com", is_active=False)

    responses = [
        await call(api_client, "POST", "/login", json={"email": EMAIL, "password": "wrong1pass"}),
        await call(
            api_client, "POST", "/login", json={"email": "nobody@example.com", "password": PASSWORD}
        ),
        await call(
            api_client,
            "POST",
            "/login",
            json={"email": "inactive@example.com", "password": PASSWORD},
        ),
    ]
    bodies = []
    for response in responses:
        error = assert_error(response, 401, "INVALID_CREDENTIALS")
        assert refresh_set_cookie(response) is None
        bodies.append((error["message"], error["details"]))
    assert len(set(map(str, bodies))) == 1


async def test_login_rehashes_outdated_hash(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    from argon2 import PasswordHasher

    old_hash = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1).hash(PASSWORD)
    user_id = await insert_user(api_conn, roles, EMAIL, password_hash=old_hash)
    await login(api_client, EMAIL)
    new_hash = await api_conn.scalar(select(User.password_hash).where(User.id == user_id))
    assert new_hash != old_hash
    assert "$m=1024,t=1,p=1$" in new_hash


async def test_login_rejects_unknown_fields(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    response = await call(
        api_client, "POST", "/login", json={"email": EMAIL, "password": PASSWORD, "x": 1}
    )
    assert_error(response, 422, "VALIDATION_ERROR")


# --------------------------------------------------------------------------
# Access token, /me, roles, must_change_password
# --------------------------------------------------------------------------


async def test_me_returns_current_user(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL, phone="700123456")
    response = await call(api_client, "GET", "/me", access=session.access)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(decode_access_token(session.access)),
        "email": EMAIL,
        "full_name": "Test User",
        "phone": "+996700123456",
        "preferred_language": "ru",
        "roles": ["customer"],
        "must_change_password": False,
        "has_password": True,
    }


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer", "Bearer garbage", "Basic dXNlcjpwYXNz", "Token abc"],
)
async def test_me_requires_valid_bearer_token(
    api_client: httpx.AsyncClient, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = await call(api_client, "GET", "/me", headers=headers)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_expired_or_foreign_tokens_are_rejected(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    user_id = decode_access_token(session.access)
    expired = create_access_token(user_id, now=datetime.now(UTC) - timedelta(minutes=16))
    unknown_user = create_access_token(uuid.uuid4())
    for token in (expired.token, unknown_user.token):
        response = await call(api_client, "GET", "/me", access=token)
        assert_error(response, 401, "UNAUTHORIZED")


async def test_deactivation_takes_effect_on_next_request(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    await api_conn.execute(update(User).where(User.email == EMAIL).values(is_active=False))
    response = await call(api_client, "GET", "/me", access=session.access)
    assert_error(response, 401, "UNAUTHORIZED")


def _add_protected_routes(app: FastAPI) -> None:
    async def any_user(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
        return {"id": str(user.id)}

    async def admin_only(
        user: Annotated[CurrentUser, Depends(require_roles(RoleName.ADMIN.value))],
    ) -> dict:
        return {"id": str(user.id)}

    async def staff(
        user: Annotated[
            CurrentUser, Depends(require_roles(RoleName.COOK.value, RoleName.COURIER.value))
        ],
    ) -> dict:
        return {"id": str(user.id)}

    app.add_api_route("/api/v1/_test/any-user", any_user)
    app.add_api_route("/api/v1/_test/admin", admin_only)
    app.add_api_route("/api/v1/_test/staff", staff)


async def _get(client: httpx.AsyncClient, path: str, access: str) -> httpx.Response:
    return await client.get(f"/api/v1/_test/{path}", headers={"Authorization": f"Bearer {access}"})


async def test_require_roles(
    app: FastAPI,
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
) -> None:
    _add_protected_routes(app)
    customer = await register(api_client, EMAIL)
    await insert_user(api_conn, roles, "cook@example.com", role_names=("cook", "customer"))
    await insert_user(api_conn, roles, "admin@example.com", role_names=("admin",))
    cook = await login(api_client, "cook@example.com")
    admin = await login(api_client, "admin@example.com")

    assert (await _get(api_client, "any-user", customer.access)).status_code == 200
    assert_error(await _get(api_client, "admin", customer.access), 403, "FORBIDDEN")
    assert_error(await _get(api_client, "staff", customer.access), 403, "FORBIDDEN")
    assert (await _get(api_client, "staff", cook.access)).status_code == 200
    assert_error(await _get(api_client, "admin", cook.access), 403, "FORBIDDEN")
    assert (await _get(api_client, "admin", admin.access)).status_code == 200


async def test_roles_are_read_from_database_on_every_request(
    app: FastAPI,
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
) -> None:
    _add_protected_routes(app)
    user_id = await insert_user(api_conn, roles, "admin@example.com", role_names=("admin",))
    admin = await login(api_client, "admin@example.com")
    assert (await _get(api_client, "admin", admin.access)).status_code == 200
    await api_conn.execute(UserRole.__table__.delete().where(UserRole.user_id == user_id))
    assert_error(await _get(api_client, "admin", admin.access), 403, "FORBIDDEN")


async def test_must_change_password_allows_only_listed_routes(
    app: FastAPI,
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
) -> None:
    _add_protected_routes(app)
    await insert_user(
        api_conn, roles, "staff@example.com", role_names=("cook",), must_change_password=True
    )
    session = await login(api_client, "staff@example.com")

    assert_error(
        await _get(api_client, "any-user", session.access), 403, "PASSWORD_CHANGE_REQUIRED"
    )
    assert_error(await _get(api_client, "staff", session.access), 403, "PASSWORD_CHANGE_REQUIRED")

    me = await call(api_client, "GET", "/me", access=session.access)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    refreshed = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert refreshed.status_code == 200  # flag is kept, session is not cut
    new_access = refreshed.json()["access_token"]
    me_again = await call(api_client, "GET", "/me", access=new_access)
    assert me_again.json()["must_change_password"] is True

    changed = await call(
        api_client,
        "POST",
        "/password/change",
        access=new_access,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204
    assert (await _get(api_client, "staff", new_access)).status_code == 200

    logout = await call(api_client, "POST", "/logout", csrf=True)
    assert logout.status_code == 204


# --------------------------------------------------------------------------
# CSRF (DEC-68, DEC-140)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/refresh", "/logout"])
@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="nothing"),
        pytest.param({"X-CSRF-Protection": "1"}, id="no-origin"),
        pytest.param({"Origin": ORIGIN}, id="no-header"),
        pytest.param({"Origin": "http://evil.example", "X-CSRF-Protection": "1"}, id="foreign"),
        pytest.param({"Origin": "null", "X-CSRF-Protection": "1"}, id="null-origin"),
        pytest.param({"Origin": ORIGIN + "/", "X-CSRF-Protection": "1"}, id="trailing-slash"),
        pytest.param({"Origin": ORIGIN, "X-CSRF-Protection": "0"}, id="header-0"),
    ],
)
async def test_csrf_is_required(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    path: str,
    headers: dict[str, str],
) -> None:
    session = await register(api_client, EMAIL)
    response = await call(api_client, "POST", path, refresh=session.refresh, headers=headers)
    assert_error(response, 403, "CSRF_FAILED")
    assert refresh_set_cookie(response) is None
    tokens = await tokens_of(api_conn, decode_access_token(session.access))
    assert all(t.revoked_at is None for t in tokens)  # nothing happened


# --------------------------------------------------------------------------
# Refresh (DEC-140 order of checks)
# --------------------------------------------------------------------------


async def test_refresh_rotates_token(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    response = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert response.status_code == 200
    new_cookie = refresh_set_cookie(response)
    assert new_cookie is not None and new_cookie.value != session.refresh
    me = await call(api_client, "GET", "/me", access=response.json()["access_token"])
    assert me.status_code == 200

    tokens = {
        t.token_hash: t for t in await tokens_of(api_conn, decode_access_token(session.access))
    }
    old = tokens[hash_refresh_token(session.refresh)]
    new = tokens[hash_refresh_token(new_cookie.value)]
    assert old.revoked_at is not None and old.replaced_by_id == new.id
    assert new.revoked_at is None and new.family_id == old.family_id


async def test_refresh_without_or_with_unknown_cookie(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    for refresh in (None, "unknown-token", "x" * 500):
        response = await call(api_client, "POST", "/refresh", refresh=refresh, csrf=True)
        assert_error(response, 401, "INVALID_REFRESH_TOKEN")
        assert refresh_set_cookie(response) is None


async def test_refresh_reuse_revokes_family(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    other = await login(api_client, EMAIL)  # second family must survive
    first = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert first.status_code == 200

    reuse = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert_error(reuse, 401, "INVALID_REFRESH_TOKEN")

    user_id = decode_access_token(session.access)
    tokens = await tokens_of(api_conn, user_id)
    other_hash = hash_refresh_token(other.refresh)
    assert all(t.revoked_at is not None for t in tokens if t.token_hash != other_hash)
    assert [t.revoked_at for t in tokens if t.token_hash == other_hash] == [None]


async def test_refresh_of_inactive_user_revokes_all(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    await login(api_client, EMAIL)
    await api_conn.execute(update(User).where(User.email == EMAIL).values(is_active=False))
    response = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert_error(response, 401, "INVALID_REFRESH_TOKEN")
    tokens = await tokens_of(api_conn, decode_access_token(session.access))
    assert len(tokens) == 2 and all(t.revoked_at is not None for t in tokens)


async def test_expired_refresh_token_revokes_nothing(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    user_id = decode_access_token(session.access)
    _, expired_raw = await create_family(
        api_conn,
        user_id,
        now=datetime.now(UTC) - timedelta(days=31),
        ttl=timedelta(days=30),
    )
    response = await call(api_client, "POST", "/refresh", refresh=expired_raw, csrf=True)
    assert_error(response, 401, "INVALID_REFRESH_TOKEN")
    assert all(t.revoked_at is None for t in await tokens_of(api_conn, user_id))


# --------------------------------------------------------------------------
# Logout
# --------------------------------------------------------------------------


async def test_logout_revokes_family_and_clears_cookie(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    other = await login(api_client, EMAIL)
    response = await call(api_client, "POST", "/logout", refresh=session.refresh, csrf=True)
    assert response.status_code == 204
    cookie = refresh_set_cookie(response)
    assert cookie is not None
    assert cookie.attributes["max-age"] == "0"
    assert cookie.attributes["path"] == "/api/v1/auth"

    tokens = await tokens_of(api_conn, decode_access_token(session.access))
    by_hash = {t.token_hash: t for t in tokens}
    assert by_hash[hash_refresh_token(session.refresh)].revoked_at is not None
    assert by_hash[hash_refresh_token(other.refresh)].revoked_at is None

    again = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert_error(again, 401, "INVALID_REFRESH_TOKEN")


@pytest.mark.parametrize("refresh", [None, "unknown-token"])
async def test_logout_always_answers_204(
    api_client: httpx.AsyncClient, refresh: str | None
) -> None:
    response = await call(api_client, "POST", "/logout", refresh=refresh, csrf=True)
    assert response.status_code == 204
    assert refresh_set_cookie(response) is not None  # cleared


async def test_logout_does_not_need_access_token(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    response = await call(api_client, "POST", "/logout", refresh=session.refresh, csrf=True)
    assert response.status_code == 204
    # The access token stays valid until it expires (accepted limitation).
    me = await call(api_client, "GET", "/me", access=session.access)
    assert me.status_code == 200


# --------------------------------------------------------------------------
# Password change
# --------------------------------------------------------------------------


async def test_password_change_revokes_all_sessions(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    await login(api_client, EMAIL)
    response = await call(
        api_client,
        "POST",
        "/password/change",
        access=session.access,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    cookie = refresh_set_cookie(response)
    assert cookie is not None and cookie.attributes["max-age"] == "0"

    tokens = await tokens_of(api_conn, decode_access_token(session.access))
    assert len(tokens) == 2 and all(t.revoked_at is not None for t in tokens)

    old = await call(api_client, "POST", "/login", json={"email": EMAIL, "password": PASSWORD})
    assert_error(old, 401, "INVALID_CREDENTIALS")
    await login(api_client, EMAIL, NEW_PASSWORD)


async def test_password_change_wrong_current_password(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    session = await register(api_client, EMAIL)
    response = await call(
        api_client,
        "POST",
        "/password/change",
        access=session.access,
        json={"current_password": "wrong1pass", "new_password": NEW_PASSWORD},
    )
    error = assert_error(response, 422, "CURRENT_PASSWORD_INVALID")  # DEC-143
    assert error["message"] == "Текущий пароль указан неверно"
    assert error["details"] == []
    assert "wrong1pass" not in response.text
    assert refresh_set_cookie(response) is None
    user_id = decode_access_token(session.access)
    tokens = await tokens_of(api_conn, user_id)
    assert all(t.revoked_at is None for t in tokens)
    await login(api_client, EMAIL)  # password unchanged


@pytest.mark.parametrize("new_password", ["short1", "lettersonly", "12345678"])
async def test_password_change_applies_policy(
    api_client: httpx.AsyncClient, roles: dict[str, uuid.UUID], new_password: str
) -> None:
    session = await register(api_client, EMAIL)
    response = await call(
        api_client,
        "POST",
        "/password/change",
        access=session.access,
        json={"current_password": PASSWORD, "new_password": new_password},
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert new_password not in response.text


async def test_password_change_requires_access_token(api_client: httpx.AsyncClient) -> None:
    response = await call(
        api_client,
        "POST",
        "/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert_error(response, 401, "UNAUTHORIZED")


# --------------------------------------------------------------------------
# Secrets never reach logs or error bodies
# --------------------------------------------------------------------------


async def test_secrets_are_not_logged(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    session = await register(api_client, EMAIL)
    refreshed = await call(api_client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    new_refresh = refresh_set_cookie(refreshed).value
    await call(api_client, "POST", "/login", json={"email": EMAIL, "password": "wrong1pass"})
    await call(
        api_client,
        "POST",
        "/password/change",
        access=refreshed.json()["access_token"],
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    password_hash = await api_conn.scalar(select(User.password_hash).where(User.email == EMAIL))
    text = caplog.text
    for secret in (
        PASSWORD,
        NEW_PASSWORD,
        "wrong1pass",
        session.access,
        session.refresh,
        new_refresh,
        password_hash,
    ):
        assert secret not in text


async def test_users_table_untouched_by_failed_registration(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    response = await call(
        api_client, "POST", "/register", json=register_body(EMAIL, password="short1")
    )
    assert response.status_code == 422
    assert await api_conn.scalar(select(func.count()).select_from(User)) == 0


async def test_csrf_headers_constant_matches_settings() -> None:
    from app.core.config import get_settings

    assert CSRF_HEADERS["Origin"] in get_settings().csrf_trusted_origins
