"""MA-1: Telegram-only accounts, `POST /auth/credentials`, `GET/PATCH /users/me`.

DEC-142 K2-B, DEC-152 пп. 2.6, 9; API_SPECIFICATION.md §2.3, §4.
Telegram-only accounts are inserted directly (their creation from the Mini
App is MA-2). Every test runs in a rolled-back transaction (api_client),
except the concurrency tests, which need real COMMITs (committing_client).
"""

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.api.v1 import auth as auth_router
from app.core.mailer import OutgoingEmail
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.users.enums import RoleName
from app.modules.users.models import PasswordResetToken, RefreshToken, Role, User, UserRole
from tests.auth_http import NEW_PASSWORD, PASSWORD, call, login, wait_for_lock_waiters
from tests.conftest import CommittedUsers

pytestmark = pytest.mark.db

Client = tuple[httpx.AsyncClient, CommittedUsers]
USERS_ME = "/api/v1/users/me"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


@pytest.fixture
async def roles(api_conn: AsyncConnection) -> dict[str, uuid.UUID]:
    rows = await api_conn.execute(
        insert(Role)
        .values([{"name": name.value} for name in RoleName])
        .returning(Role.name, Role.id)
    )
    return {name: role_id for name, role_id in rows.all()}


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[OutgoingEmail]:
    sent: list[OutgoingEmail] = []

    def capture(message: OutgoingEmail) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(auth_router, "send_email", capture)
    return sent


async def add_user(
    conn: Any,
    role_ids: dict[str, uuid.UUID],
    *,
    email: str | None = None,
    role_names: tuple[str, ...] = ("customer",),
    full_name: str = "Telegram User",
    **values: Any,
) -> uuid.UUID:
    """Insert a user; without `email` it is a Telegram-only account."""
    user_id = await conn.scalar(
        insert(User)
        .values(
            email=email,
            password_hash=hash_password(PASSWORD) if email else None,
            full_name=full_name,
            **values,
        )
        .returning(User.id)
    )
    for name in role_names:
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_ids[name]))
    return user_id


def bearer(user_id: uuid.UUID) -> str:
    return create_access_token(user_id).token


async def credentials(client: httpx.AsyncClient, user_id: uuid.UUID, body: Any) -> httpx.Response:
    return await call(client, "POST", "/credentials", access=bearer(user_id), json=body)


async def me_request(
    client: httpx.AsyncClient,
    method: str,
    user_id: uuid.UUID | None,
    body: Any = None,
    *,
    token: str | None = None,
) -> httpx.Response:
    headers = {}
    if token is not None or user_id is not None:
        headers["Authorization"] = f"Bearer {token or bearer(user_id)}"
    return await client.request(method, USERS_ME, json=body, headers=headers)


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


async def user_row(conn: Any, user_id: uuid.UUID) -> Any:
    return (
        await conn.execute(
            select(
                User.email,
                User.password_hash,
                User.full_name,
                User.phone,
                User.preferred_language,
                User.is_active,
                User.is_verified,
                User.must_change_password,
                User.updated_at,
            ).where(User.id == user_id)
        )
    ).one()


async def role_names_of(conn: Any, user_id: uuid.UUID) -> set[str]:
    rows = await conn.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return set(rows.all())


# --------------------------------------------------------------------------
# Telegram-only account: /auth/me, login, forgot, password change
# --------------------------------------------------------------------------


async def test_me_of_telegram_only_account(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles)
    response = await call(api_client, "GET", "/me", access=bearer(user_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] is None
    assert body["has_password"] is False
    assert body["roles"] == ["customer"]


async def test_login_and_forgot_do_not_find_telegram_only_account(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    outbox: list[OutgoingEmail],
) -> None:
    await add_user(api_conn, roles)
    unknown = {"email": "nobody@example.com", "password": PASSWORD}
    assert_error(await call(api_client, "POST", "/login", json=unknown), 401, "INVALID_CREDENTIALS")
    forgot = await call(
        api_client, "POST", "/password/forgot", json={"email": "nobody@example.com"}
    )
    assert forgot.status_code == 202
    assert outbox == []
    assert await api_conn.scalar(select(func.count()).select_from(PasswordResetToken)) == 0
    assert await api_conn.scalar(select(func.count()).select_from(RefreshToken)) == 0


async def test_password_change_without_password_is_409(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles)
    before = await user_row(api_conn, user_id)
    response = await call(
        api_client,
        "POST",
        "/password/change",
        access=bearer(user_id),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert_error(response, 409, "PASSWORD_NOT_SET")
    assert await user_row(api_conn, user_id) == before


async def test_password_change_with_password_is_unchanged(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    """Regression: an account with a password still gets 422 for a wrong one."""
    user_id = await add_user(api_conn, roles, email="site@example.com")
    response = await call(
        api_client,
        "POST",
        "/password/change",
        access=bearer(user_id),
        json={"current_password": "wrong1password", "new_password": NEW_PASSWORD},
    )
    assert_error(response, 422, "CURRENT_PASSWORD_INVALID")


# --------------------------------------------------------------------------
# POST /auth/credentials
# --------------------------------------------------------------------------


async def test_credentials_are_added_and_enable_site_login_and_reset(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    outbox: list[OutgoingEmail],
) -> None:
    user_id = await add_user(api_conn, roles, full_name="Айгуль", preferred_language="ky")
    before = await user_row(api_conn, user_id)

    response = await credentials(
        api_client, user_id, {"email": "  New.User@Example.COM ", "password": PASSWORD}
    )
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert "set-cookie" not in response.headers

    row = await user_row(api_conn, user_id)
    assert row.email == "new.user@example.com"  # normalized as at registration
    assert row.password_hash.startswith("$argon2id$")
    assert verify_password(row.password_hash, PASSWORD)
    # Nothing else changed.
    assert (row.full_name, row.phone, row.preferred_language) == ("Айгуль", None, "ky")
    assert (row.is_active, row.is_verified, row.must_change_password) == (
        before.is_active,
        before.is_verified,
        before.must_change_password,
    )
    assert await role_names_of(api_conn, user_id) == {"customer"}

    me = (await call(api_client, "GET", "/me", access=bearer(user_id))).json()
    assert me["email"] == "new.user@example.com"
    assert me["has_password"] is True

    session = await login(api_client, "NEW.USER@example.com")
    assert session.access
    forgot = await call(
        api_client, "POST", "/password/forgot", json={"email": "new.user@example.com"}
    )
    assert forgot.status_code == 202
    assert [message.to for message in outbox] == ["new.user@example.com"]


async def test_credentials_twice_is_409_and_keeps_first(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles)
    first = await credentials(
        api_client, user_id, {"email": "first@example.com", "password": PASSWORD}
    )
    assert first.status_code == 204
    after_first = await user_row(api_conn, user_id)

    again = await credentials(
        api_client, user_id, {"email": "second@example.com", "password": NEW_PASSWORD}
    )
    assert_error(again, 409, "CREDENTIALS_ALREADY_SET")
    same = await credentials(
        api_client, user_id, {"email": "first@example.com", "password": PASSWORD}
    )
    assert_error(same, 409, "CREDENTIALS_ALREADY_SET")
    assert await user_row(api_conn, user_id) == after_first


async def test_credentials_of_site_account_is_409_and_never_overwrites(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles, email="site@example.com")
    before = await user_row(api_conn, user_id)
    response = await credentials(
        api_client, user_id, {"email": "other@example.com", "password": NEW_PASSWORD}
    )
    assert_error(response, 409, "CREDENTIALS_ALREADY_SET")
    assert await user_row(api_conn, user_id) == before


@pytest.mark.parametrize("taken", ["taken@example.com", "TAKEN@Example.com"])
async def test_credentials_with_taken_email_is_409(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    taken: str,
) -> None:
    await add_user(api_conn, roles, email="taken@example.com")
    user_id = await add_user(api_conn, roles)
    before = await user_row(api_conn, user_id)
    response = await credentials(api_client, user_id, {"email": taken, "password": PASSWORD})
    assert_error(response, 409, "EMAIL_ALREADY_EXISTS")
    assert await user_row(api_conn, user_id) == before


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "", "password": PASSWORD},
        {"email": "a" * 250 + "@example.com", "password": PASSWORD},
        {"email": "x@example.com", "password": "short1"},
        {"email": "x@example.com", "password": "lettersonly"},
        {"email": "x@example.com", "password": "123456789"},
        {"email": "x@example.com", "password": "a1" * 65},
        {"email": "x@example.com"},
        {"password": PASSWORD},
        {"email": "x@example.com", "password": PASSWORD, "role": "admin"},
        {"email": "x@example.com", "password": PASSWORD, "user_id": str(uuid.uuid4())},
        {"email": None, "password": None},
    ],
)
async def test_credentials_validation(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    body: dict[str, Any],
) -> None:
    user_id = await add_user(api_conn, roles)
    before = await user_row(api_conn, user_id)
    response = await credentials(api_client, user_id, body)
    assert_error(response, 422, "VALIDATION_ERROR")
    password = body.get("password")
    if password:
        assert password not in response.text  # never echoed (DEC-152 п. 4)
    assert await user_row(api_conn, user_id) == before


async def test_credentials_require_authentication(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    body = {"email": "x@example.com", "password": PASSWORD}
    assert_error(await call(api_client, "POST", "/credentials", json=body), 401, "UNAUTHORIZED")
    user_id = await add_user(api_conn, roles, is_active=False)
    assert_error(await credentials(api_client, user_id, body), 401, "UNAUTHORIZED")
    assert (await user_row(api_conn, user_id)).email is None


async def test_credentials_password_is_not_logged(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    user_id = await add_user(api_conn, roles)
    secret = "unique7secret"  # noqa: S105 - test data
    assert (
        await credentials(api_client, user_id, {"email": "log@example.com", "password": secret})
    ).status_code == 204
    other = await add_user(api_conn, roles)
    await credentials(api_client, other, {"email": "bad", "password": "another9secret"})
    assert secret not in caplog.text
    assert "another9secret" not in caplog.text


# --------------------------------------------------------------------------
# POST /auth/credentials under concurrency (real COMMITs)
# --------------------------------------------------------------------------


async def _committed_role_ids(engine: AsyncEngine) -> dict[str, uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(Role.name, Role.id))
        return {name: role_id for name, role_id in rows.all()}


async def _committed_telegram_user(engine: AsyncEngine, users: CommittedUsers) -> uuid.UUID:
    role_ids = await _committed_role_ids(engine)
    async with engine.begin() as conn:
        user_id = await add_user(conn, role_ids)
    users.track(user_id)
    return user_id


async def _committed_credentials(engine: AsyncEngine, user_id: uuid.UUID) -> tuple:
    async with engine.connect() as conn:
        return tuple(
            (
                await conn.execute(select(User.email, User.password_hash).where(User.id == user_id))
            ).one()
        )


async def test_concurrent_credentials_for_one_account(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    user_id = await _committed_telegram_user(async_engine, users)
    emails = [users.new_email(), users.new_email()]

    # Hold the user row so both requests reach their UPDATE, then release.
    async with async_engine.connect() as blocker:
        transaction = await blocker.begin()
        await blocker.execute(
            select(User.id).where(User.id == user_id).with_for_update(key_share=True)
        )
        tasks = [
            asyncio.create_task(credentials(client, user_id, {"email": e, "password": PASSWORD}))
            for e in emails
        ]
        await wait_for_lock_waiters(async_engine, 2)
        await transaction.rollback()
        responses = await asyncio.gather(*tasks)

    assert sorted(r.status_code for r in responses) == [204, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["error"]["code"] == "CREDENTIALS_ALREADY_SET"
    winner_email = emails[[r.status_code for r in responses].index(204)]
    email, password_hash = await _committed_credentials(async_engine, user_id)
    assert email == winner_email
    assert password_hash is not None


async def test_concurrent_credentials_with_same_email(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    first = await _committed_telegram_user(async_engine, users)
    second = await _committed_telegram_user(async_engine, users)
    email = users.new_email()

    async with async_engine.connect() as blocker:
        transaction = await blocker.begin()
        await blocker.execute(
            select(User.id).where(User.id.in_([first, second])).with_for_update(key_share=True)
        )
        tasks = [
            asyncio.create_task(credentials(client, uid, {"email": email, "password": PASSWORD}))
            for uid in (first, second)
        ]
        await wait_for_lock_waiters(async_engine, 2)
        await transaction.rollback()
        responses = await asyncio.gather(*tasks)

    assert sorted(r.status_code for r in responses) == [204, 409]
    loser_index = [r.status_code for r in responses].index(409)
    assert responses[loser_index].json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    # Exactly one account owns the email; the other is unchanged.
    assert await _committed_credentials(async_engine, (first, second)[loser_index]) == (None, None)
    async with async_engine.connect() as conn:
        owners = await conn.scalar(
            select(func.count()).select_from(User).where(func.lower(User.email) == email)
        )
    assert owners == 1


async def test_credentials_waiting_for_deactivation_is_refused(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    user_id = await _committed_telegram_user(async_engine, users)

    async with async_engine.connect() as admin:
        transaction = await admin.begin()
        await admin.execute(update(User).where(User.id == user_id).values(is_active=False))
        task = asyncio.create_task(
            credentials(client, user_id, {"email": users.new_email(), "password": PASSWORD})
        )
        await wait_for_lock_waiters(async_engine, 1)
        await transaction.commit()
        response = await task

    assert_error(response, 401, "UNAUTHORIZED")
    assert await _committed_credentials(async_engine, user_id) == (None, None)


# --------------------------------------------------------------------------
# GET /users/me
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "role_names"),
    [(None, ("customer",)), ("site@example.com", ("customer",)), ("cook@example.com", ("cook",))],
)
async def test_get_profile(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    email: str | None,
    role_names: tuple[str, ...],
) -> None:
    user_id = await add_user(
        api_conn, roles, email=email, role_names=role_names, phone="+996700123456"
    )
    response = await me_request(api_client, "GET", user_id)
    assert response.status_code == 200, response.text
    auth_me = (await call(api_client, "GET", "/me", access=bearer(user_id))).json()
    assert response.json() == auth_me  # same body as GET /auth/me
    assert response.json()["id"] == str(user_id)
    assert response.json()["email"] == email
    assert response.json()["has_password"] is (email is not None)


async def test_profile_requires_valid_token(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    for method in ("GET", "PATCH"):
        body = {"full_name": "X"} if method == "PATCH" else None
        assert_error(await me_request(api_client, method, None, body), 401, "UNAUTHORIZED")
        assert_error(
            await me_request(api_client, method, None, body, token="garbage"), 401, "UNAUTHORIZED"
        )
        unknown = await me_request(api_client, method, uuid.uuid4(), body)
        assert_error(unknown, 401, "UNAUTHORIZED")
    inactive = await add_user(api_conn, roles, is_active=False)
    assert_error(await me_request(api_client, "GET", inactive), 401, "UNAUTHORIZED")
    assert_error(
        await me_request(api_client, "PATCH", inactive, {"full_name": "New"}), 401, "UNAUTHORIZED"
    )
    assert (await user_row(api_conn, inactive)).full_name == "Telegram User"


async def test_profile_while_password_change_required(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(
        api_conn, roles, email="staff@example.com", role_names=("cook",), must_change_password=True
    )
    assert_error(await me_request(api_client, "GET", user_id), 403, "PASSWORD_CHANGE_REQUIRED")
    assert_error(
        await me_request(api_client, "PATCH", user_id, {"full_name": "New"}),
        403,
        "PASSWORD_CHANGE_REQUIRED",
    )
    assert (await user_row(api_conn, user_id)).full_name == "Telegram User"


# --------------------------------------------------------------------------
# PATCH /users/me
# --------------------------------------------------------------------------


async def test_patch_profile_changes_allowed_fields(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles)
    before = await user_row(api_conn, user_id)

    response = await me_request(
        api_client,
        "PATCH",
        user_id,
        {"full_name": "  Азамат Осмонов ", "phone": "0700 12 34 56", "preferred_language": "uz"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Азамат Осмонов"
    assert body["phone"] == "+996700123456"
    assert body["preferred_language"] == "uz"
    assert body["email"] is None and body["has_password"] is False

    row = await user_row(api_conn, user_id)
    assert (row.full_name, row.phone, row.preferred_language) == (
        "Азамат Осмонов",
        "+996700123456",
        "uz",
    )
    assert (row.email, row.password_hash, row.is_active, row.must_change_password) == (
        None,
        None,
        True,
        False,
    )
    assert row.updated_at >= before.updated_at
    assert await role_names_of(api_conn, user_id) == {"customer"}
    auth_me = (await call(api_client, "GET", "/me", access=bearer(user_id))).json()
    assert auth_me == body


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"full_name": "Only Name"}, ("Only Name", "+996700123456", "ru")),
        ({"phone": "+996 555 00 11 22"}, ("Telegram User", "+996555001122", "ru")),
        ({"phone": None}, ("Telegram User", None, "ru")),
        ({"preferred_language": "ky"}, ("Telegram User", "+996700123456", "ky")),
        ({}, ("Telegram User", "+996700123456", "ru")),
    ],
)
async def test_patch_profile_is_partial(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    body: dict[str, Any],
    expected: tuple,
) -> None:
    user_id = await add_user(api_conn, roles, email="site@example.com", phone="+996700123456")
    response = await me_request(api_client, "PATCH", user_id, body)
    assert response.status_code == 200, response.text
    row = await user_row(api_conn, user_id)
    assert (row.full_name, row.phone, row.preferred_language) == expected
    assert (response.json()["full_name"], response.json()["phone"]) == expected[:2]
    assert row.email == "site@example.com"


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": None},
        {"full_name": ""},
        {"full_name": "   "},
        {"full_name": "x" * 151},
        {"full_name": "Bad\u0007Name"},
        {"phone": "12345"},
        {"phone": "+997700123456"},
        {"preferred_language": None},
        {"preferred_language": "en"},
        {"full_name": 123},
        [],
        "text",
    ],
)
async def test_patch_profile_validation(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID], body: Any
) -> None:
    user_id = await add_user(api_conn, roles, phone="+996700123456")
    before = await user_row(api_conn, user_id)
    assert_error(await me_request(api_client, "PATCH", user_id, body), 422, "VALIDATION_ERROR")
    assert await user_row(api_conn, user_id) == before


async def test_patch_profile_counts_unicode_characters(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    user_id = await add_user(api_conn, roles)
    name = "Ө" * 150
    response = await me_request(api_client, "PATCH", user_id, {"full_name": name})
    assert response.status_code == 200, response.text
    assert (await user_row(api_conn, user_id)).full_name == name


@pytest.mark.parametrize(
    "forbidden",
    [
        {"email": "new@example.com"},
        {"password": PASSWORD},
        {"password_hash": "x"},
        {"roles": ["admin"]},
        {"role": "admin"},
        {"is_active": False},
        {"is_verified": True},
        {"must_change_password": True},
        {"has_password": True},
        {"id": str(uuid.uuid4())},
        {"user_id": str(uuid.uuid4())},
        {"created_at": "2020-01-01T00:00:00Z"},
    ],
)
async def test_patch_profile_rejects_other_fields(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
    forbidden: dict[str, Any],
) -> None:
    user_id = await add_user(api_conn, roles, email="site@example.com")
    before = await user_row(api_conn, user_id)
    body = {"full_name": "Changed", **forbidden}
    assert_error(await me_request(api_client, "PATCH", user_id, body), 422, "VALIDATION_ERROR")
    assert await user_row(api_conn, user_id) == before
    assert await role_names_of(api_conn, user_id) == {"customer"}


async def test_patch_profile_changes_only_own_account(
    api_client: httpx.AsyncClient, api_conn: AsyncConnection, roles: dict[str, uuid.UUID]
) -> None:
    me = await add_user(api_conn, roles)
    other = await add_user(api_conn, roles, email="other@example.com", full_name="Other")
    other_before = await user_row(api_conn, other)

    # A foreign id in the body is an unknown field, never a target.
    assert_error(
        await me_request(api_client, "PATCH", me, {"id": str(other), "full_name": "Hacked"}),
        422,
        "VALIDATION_ERROR",
    )
    response = await me_request(api_client, "PATCH", me, {"full_name": "Mine"})
    assert response.status_code == 200
    assert response.json()["id"] == str(me)
    assert await user_row(api_conn, other) == other_before
    # GET returns only the caller's own profile.
    assert (await me_request(api_client, "GET", other)).json()["full_name"] == "Other"


async def test_patch_profile_by_staff_keeps_roles(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: dict[str, uuid.UUID],
) -> None:
    user_id = await add_user(api_conn, roles, email="courier@example.com", role_names=("courier",))
    response = await me_request(api_client, "PATCH", user_id, {"preferred_language": "ky"})
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["courier"]
    assert await role_names_of(api_conn, user_id) == {"courier"}
