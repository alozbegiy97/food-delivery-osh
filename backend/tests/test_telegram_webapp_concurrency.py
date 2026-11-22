"""Mini App register/link under concurrency, with real COMMITs (committing_client).

DEC-152 п. 3, DEC-154 пп. 3-5, U1. Order is never left to chance (no sleeps,
no assumption that PostgreSQL grants waiting locks FIFO): a controlling
transaction holds the lock a request needs, the test waits until
pg_stat_activity shows the request waiting for exactly that kind of lock
(`advisory`, a row, or a relation) and only then releases it. Final states
are read on separate connections, so only committed data is seen.
"""

import asyncio
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import get_settings
from app.core.security import decode_access_token, hash_password, verify_password
from app.modules.notifications.models import TelegramLink
from app.modules.telegram_auth.locks import LOCK_NAMESPACE, fold_telegram_id
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole
from tests.auth_http import NEW_PASSWORD, PASSWORD
from tests.conftest import CommittedUsers
from tests.telegram_init_data import TEST_BOT_TOKEN, init_data

pytestmark = pytest.mark.db

Client = tuple[httpx.AsyncClient, CommittedUsers]
WEBAPP = "/api/v1/auth/telegram/webapp"
TG = 611000001
TG_OTHER = 611000002
REQUEST_LIMIT_S = 30  # a hang fails the test instead of blocking the run


@pytest.fixture(autouse=True)
def telegram_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def wait_for_waiters(
    engine: AsyncEngine, *, advisory: int = 0, row: int = 0, relation: int = 0, limit_s: float = 10
) -> None:
    """Wait until backends of this database wait for these kinds of locks."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_s
    wanted = {"advisory": advisory, "row": row, "relation": relation}
    while True:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT wait_event, count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "GROUP BY wait_event"
                    )
                )
            ).all()
        seen = {"advisory": 0, "row": 0, "relation": 0}
        for event, count in rows:
            if event == "advisory":
                seen["advisory"] += count
            elif event == "relation":
                seen["relation"] += count
            else:  # transactionid / tuple: waiting for a row lock
                seen["row"] += count
        if all(seen[kind] >= n for kind, n in wanted.items()):
            return
        if loop.time() > deadline:
            raise AssertionError(f"expected waiters {wanted}, got {seen}")
        await asyncio.sleep(0.02)


async def post(client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(f"{WEBAPP}{path}", json=body)


def start(client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> asyncio.Task:
    return asyncio.create_task(asyncio.wait_for(post(client, path, body), REQUEST_LIMIT_S))


def register_body(telegram_id: int = TG, **user_fields: Any) -> dict[str, str]:
    return {"init_data": init_data(telegram_id=telegram_id, **user_fields)}


def link_body(email: str, telegram_id: int = TG, **user_fields: Any) -> dict[str, str]:
    return {
        "init_data": init_data(telegram_id=telegram_id, **user_fields),
        "email": email,
        "password": PASSWORD,
    }


def code(response: httpx.Response) -> str | None:
    return response.json().get("error", {}).get("code") if response.status_code != 200 else None


def subject(response: httpx.Response) -> uuid.UUID:
    assert response.status_code == 200, response.text
    assert "set-cookie" not in response.headers
    return decode_access_token(response.json()["access_token"])


async def site_user(engine: AsyncEngine, users: CommittedUsers) -> tuple[uuid.UUID, str]:
    email = users.new_email()
    async with engine.begin() as conn:
        role_id = await conn.scalar(select(Role.id).where(Role.name == RoleName.CUSTOMER.value))
        user_id = await conn.scalar(
            insert(User)
            .values(
                email=email,
                password_hash=hash_password(PASSWORD),
                full_name="Сайт Клиент",
                phone="+996700123456",
                preferred_language="ky",
            )
            .returning(User.id)
        )
        await conn.execute(insert(UserRole).values(user_id=user_id, role_id=role_id))
    users.track(user_id)
    return user_id, email


async def state(engine: AsyncEngine) -> dict[str, Any]:
    """Committed rows, read on a fresh connection."""
    async with engine.connect() as conn:
        links = {
            row.telegram_chat_id: (row.user_id, row.telegram_username, row.is_active, row.linked_at)
            for row in (
                await conn.execute(
                    select(
                        TelegramLink.telegram_chat_id,
                        TelegramLink.user_id,
                        TelegramLink.telegram_username,
                        TelegramLink.is_active,
                        TelegramLink.linked_at,
                    )
                )
            ).all()
        }
        users = int(await conn.scalar(select(func.count()).select_from(User)) or 0)
        user_roles = int(await conn.scalar(select(func.count()).select_from(UserRole)) or 0)
        return {"links": links, "users": users, "user_roles": user_roles}


async def profile(engine: AsyncEngine, user_id: uuid.UUID) -> tuple:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    User.email,
                    User.password_hash,
                    User.full_name,
                    User.phone,
                    User.preferred_language,
                    User.is_active,
                    User.updated_at,
                ).where(User.id == user_id)
            )
        ).one()
        roles = set(
            (
                await conn.scalars(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id)
                )
            ).all()
        )
    return (*row, frozenset(roles))


async def hold_advisory(conn: AsyncConnection, telegram_id: int) -> None:
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:ns AS integer), CAST(:key AS integer))"),
        {"ns": LOCK_NAMESPACE, "key": fold_telegram_id(telegram_id)},
    )


async def hold_user_row(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await conn.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))


async def gather(*tasks: asyncio.Task) -> list[httpx.Response]:
    return list(await asyncio.gather(*tasks))


# --------------------------------------------------------------------------
# 1. register + register, one Telegram ID
# --------------------------------------------------------------------------


async def test_concurrent_registrations_create_one_account(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    before = await state(async_engine)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_advisory(blocker, TG)
        tasks = [start(client, "/register", register_body(username="first")) for _ in range(2)]
        await wait_for_waiters(async_engine, advisory=2)  # both really wait
        await tx.rollback()
        responses = await gather(*tasks)

    ids = {subject(r) for r in responses}
    assert len(ids) == 1
    (user_id,) = ids
    users.track(user_id)
    after = await state(async_engine)
    assert after["users"] == before["users"] + 1
    assert after["user_roles"] == before["user_roles"] + 1
    assert after["links"] == {**before["links"], TG: after["links"][TG]}
    assert after["links"][TG][:2] == (user_id, "first")
    email, password_hash, *_, roles = await profile(async_engine, user_id)
    assert (email, password_hash, roles) == (None, None, frozenset({"customer"}))


# --------------------------------------------------------------------------
# 2. register + link, one Telegram ID, both orders made explicit
# --------------------------------------------------------------------------


async def test_register_first_then_link_is_refused(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    """register holds the advisory lock (blocked on telegram_links) while
    link waits for that advisory lock: register wins, link gets 409."""
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    site_before = await profile(async_engine, site_id)
    before = await state(async_engine)

    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await blocker.execute(text("LOCK TABLE telegram_links IN SHARE MODE"))
        register = start(client, "/register", register_body())
        await wait_for_waiters(async_engine, relation=1)  # register: after advisory
        link = start(client, "/link", link_body(email))
        await wait_for_waiters(async_engine, relation=1, advisory=1)  # link: on advisory
        await tx.rollback()
        reg_response, link_response = await gather(register, link)

    new_id = subject(reg_response)
    users.track(new_id)
    assert new_id != site_id
    assert (link_response.status_code, code(link_response)) == (409, "TELEGRAM_ALREADY_LINKED")
    after = await state(async_engine)
    assert after["users"] == before["users"] + 1
    assert after["links"][TG][0] == new_id
    assert len(after["links"]) == len(before["links"]) + 1  # nothing for the site account
    assert await profile(async_engine, site_id) == site_before


async def test_link_first_then_register_logs_into_the_site_account(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    """link holds the advisory lock (blocked on the users row) while register
    waits for it: link wins, register logs into the linked site account."""
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    before = await state(async_engine)

    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_user_row(blocker, site_id)
        link = start(client, "/link", link_body(email))
        await wait_for_waiters(async_engine, row=1)  # link: after advisory, on users
        register = start(client, "/register", register_body())
        await wait_for_waiters(async_engine, row=1, advisory=1)  # register: on advisory
        await tx.rollback()
        link_response, reg_response = await gather(link, register)

    assert subject(link_response) == site_id
    assert subject(reg_response) == site_id  # no second account
    after = await state(async_engine)
    assert after["users"] == before["users"]
    assert after["user_roles"] == before["user_roles"]
    assert after["links"][TG][0] == site_id
    assert len(after["links"]) == len(before["links"]) + 1


# --------------------------------------------------------------------------
# 3. two Telegram IDs link one site account
# --------------------------------------------------------------------------


async def test_two_telegram_ids_for_one_account(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_user_row(blocker, site_id)
        tasks = [
            start(client, "/link", link_body(email, TG)),
            start(client, "/link", link_body(email, TG_OTHER)),
        ]
        # Different advisory keys: both pass them and queue on the users row.
        await wait_for_waiters(async_engine, row=2)
        await tx.rollback()
        responses = await gather(*tasks)

    outcomes = sorted((r.status_code, code(r)) for r in responses)
    assert outcomes == [(200, None), (409, "ACCOUNT_ALREADY_LINKED")]
    winner = (TG, TG_OTHER)[[r.status_code for r in responses].index(200)]
    loser = TG_OTHER if winner == TG else TG
    links = (await state(async_engine))["links"]
    assert links[winner][0] == site_id
    assert loser not in links  # the losing Telegram is linked to nobody
    assert [chat for chat, value in links.items() if value[0] == site_id] == [winner]


# --------------------------------------------------------------------------
# 4-6. link against deactivation, password change, role removal
# --------------------------------------------------------------------------


async def _race_with(
    committing_client: Client,
    async_engine: AsyncEngine,
    change: Any,
    *,
    commit: bool,
) -> tuple[httpx.Response, uuid.UUID]:
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    async with async_engine.connect() as admin:
        tx = await admin.begin()
        await hold_user_row(admin, site_id)  # same order as staff/admin code
        await change(admin, site_id)
        link = start(client, "/link", link_body(email))
        await wait_for_waiters(async_engine, row=1)
        await (tx.commit() if commit else tx.rollback())
        (response,) = await gather(link)
    return response, site_id


async def _deactivate(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await conn.execute(update(User).where(User.id == user_id).values(is_active=False))


async def _change_password(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await conn.execute(
        update(User).where(User.id == user_id).values(password_hash=hash_password(NEW_PASSWORD))
    )


async def _remove_customer(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    role_id = select(Role.id).where(Role.name == RoleName.CUSTOMER.value).scalar_subquery()
    await conn.execute(
        delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )


@pytest.mark.parametrize(
    ("change", "status", "error_code"),
    [
        (_deactivate, 401, "INVALID_CREDENTIALS"),
        (_change_password, 401, "INVALID_CREDENTIALS"),
        (_remove_customer, 403, "FORBIDDEN"),
    ],
    ids=["deactivation", "password-change", "role-removal"],
)
async def test_link_loses_against_a_committed_change(
    committing_client: Client,
    async_engine: AsyncEngine,
    change: Any,
    status: int,
    error_code: str,
) -> None:
    before = await state(async_engine)
    response, site_id = await _race_with(committing_client, async_engine, change, commit=True)
    assert (response.status_code, code(response)) == (status, error_code)
    after = await state(async_engine)
    assert after["links"] == before["links"]  # full rollback: no link
    email, password_hash, *_, is_active, _, roles = await profile(async_engine, site_id)
    if change is _deactivate:
        assert is_active is False
    if change is _change_password:
        assert verify_password(password_hash, NEW_PASSWORD)  # the new hash stays
    if change is _remove_customer:
        assert roles == frozenset()  # only the competing change, nothing else


@pytest.mark.parametrize(
    "change",
    [_deactivate, _change_password, _remove_customer],
    ids=["deactivation", "password-change", "role-removal"],
)
async def test_link_waits_and_succeeds_when_the_change_rolls_back(
    committing_client: Client, async_engine: AsyncEngine, change: Any
) -> None:
    response, site_id = await _race_with(committing_client, async_engine, change, commit=False)
    assert subject(response) == site_id
    assert (await state(async_engine))["links"][TG][0] == site_id


# --------------------------------------------------------------------------
# 7. the same pair linked twice at once
# --------------------------------------------------------------------------


async def test_same_pair_linked_concurrently(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    site_before = await profile(async_engine, site_id)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_advisory(blocker, TG)
        tasks = [
            start(client, "/link", link_body(email, username="first")),
            start(client, "/link", link_body(email, username="second")),
        ]
        await wait_for_waiters(async_engine, advisory=2)
        await tx.rollback()
        responses = await gather(*tasks)

    assert [subject(r) for r in responses] == [site_id, site_id]
    links = (await state(async_engine))["links"]
    assert TG in links
    assert sum(1 for value in links.values() if value[0] == site_id) == 1
    assert links[TG][1] in {"first", "second"}  # written once, by the winner
    assert await profile(async_engine, site_id) == site_before


# --------------------------------------------------------------------------
# 8. two Telegram IDs with the same advisory key
# --------------------------------------------------------------------------


async def test_fold_collision_only_serializes(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    first, second = TG, TG ^ (1 << 32) ^ 1
    assert fold_telegram_id(first) == fold_telegram_id(second)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_advisory(blocker, first)  # also blocks `second`
        tasks = [
            start(client, "/register", register_body(first)),
            start(client, "/register", register_body(second)),
        ]
        await wait_for_waiters(async_engine, advisory=2)
        await tx.rollback()
        responses = await gather(*tasks)

    ids = [subject(r) for r in responses]
    for user_id in ids:
        users.track(user_id)
    assert ids[0] != ids[1]
    links = (await state(async_engine))["links"]
    assert links[first][0] == ids[0] and links[second][0] == ids[1]


# --------------------------------------------------------------------------
# 9. login and same-pair link raise is_active at the same time
# --------------------------------------------------------------------------


async def test_login_and_relink_raise_is_active_together(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    first = await post(client, "/link", link_body(email, allows_write_to_pm=False))
    assert subject(first) == site_id
    linked = (await state(async_engine))["links"][TG]
    assert linked[2] is False

    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await blocker.execute(
            select(TelegramLink.id).where(TelegramLink.telegram_chat_id == TG).with_for_update()
        )
        tasks = [
            start(client, "", register_body(allows_write_to_pm=True)),
            start(client, "/link", link_body(email, allows_write_to_pm=True)),
        ]
        await wait_for_waiters(async_engine, row=2)  # both wait for the link row
        await tx.rollback()
        responses = await gather(*tasks)

    assert [subject(r) for r in responses] == [site_id, site_id]
    final = (await state(async_engine))["links"]
    assert final == {TG: (site_id, linked[1], True, linked[3])}


# --------------------------------------------------------------------------
# U1: 5 s lock_timeout -> 409 TELEGRAM_BUSY, rollback, connection reusable
# --------------------------------------------------------------------------


async def test_register_lock_timeout_is_busy_and_rolls_back(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    before = await state(async_engine)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_advisory(blocker, TG)
        started = time.monotonic()
        response = await asyncio.wait_for(post(client, "/register", register_body()), 20)
        elapsed = time.monotonic() - started
        await tx.rollback()

    assert (response.status_code, code(response)) == (409, "TELEGRAM_BUSY")
    assert 4.5 <= elapsed < 15
    assert "lock" not in response.text.lower()  # no PostgreSQL message leaks
    assert await state(async_engine) == before
    # The application keeps working on its pooled connections.
    users.track(subject(await post(client, "/register", register_body())))


async def test_link_lock_timeout_is_busy_and_rolls_back(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    site_id, email = await site_user(async_engine, users)
    before = await state(async_engine)
    async with async_engine.connect() as blocker:
        tx = await blocker.begin()
        await hold_user_row(blocker, site_id)
        started = time.monotonic()
        response = await asyncio.wait_for(post(client, "/link", link_body(email)), 20)
        elapsed = time.monotonic() - started
        await tx.rollback()

    assert (response.status_code, code(response)) == (409, "TELEGRAM_BUSY")
    assert 4.5 <= elapsed < 15
    assert await state(async_engine) == before
    assert subject(await post(client, "/link", link_body(email))) == site_id
