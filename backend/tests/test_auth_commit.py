"""`/auth` with real COMMITs (committing_client; S3-B, DEC-140).

Covers what one rolled-back transaction cannot show: visibility from
another connection, row locks between concurrent requests, the unique
email index under concurrency, the isolation level inside refresh and the
behaviour when COMMIT fails. Also a read-only guard on the ON DELETE
actions the test cleanup relies on.

Limitation: COMMIT failures are simulated by patching
`AsyncSession.commit`; this does not reproduce every way a connection can
be lost during a real COMMIT.
"""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import decode_access_token, hash_password, verify_password
from app.modules.auth import service
from app.modules.auth.refresh_sessions import hash_refresh_token
from app.modules.users.models import RefreshToken, User
from tests.auth_http import (
    NEW_PASSWORD,
    PASSWORD,
    call,
    refresh_set_cookie,
    register,
    register_body,
    wait_for_lock_waiters,
)
from tests.conftest import CommittedUsers

pytestmark = pytest.mark.db

Client = tuple[httpx.AsyncClient, CommittedUsers]


async def committed_tokens(engine: AsyncEngine, user_id: uuid.UUID) -> list:
    """Read on a separate connection: only committed rows are visible."""
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    select(
                        RefreshToken.id,
                        RefreshToken.family_id,
                        RefreshToken.token_hash,
                        RefreshToken.revoked_at,
                    ).where(RefreshToken.user_id == user_id)
                )
            ).all()
        )


# --------------------------------------------------------------------------
# Results are committed before the response
# --------------------------------------------------------------------------


async def test_refused_refresh_revocation_is_committed(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    assert (
        await call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    ).status_code == 200
    reuse = await call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert reuse.status_code == 401
    tokens = await committed_tokens(async_engine, decode_access_token(session.access))
    assert len(tokens) == 2 and all(t.revoked_at is not None for t in tokens)


async def test_logout_revocation_is_committed(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    response = await call(client, "POST", "/logout", refresh=session.refresh, csrf=True)
    assert response.status_code == 204
    tokens = await committed_tokens(async_engine, decode_access_token(session.access))
    assert [t.revoked_at is not None for t in tokens] == [True]


async def test_password_change_is_committed(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    email = users.new_email()
    session = await register(client, email)
    response = await call(
        client,
        "POST",
        "/password/change",
        access=session.access,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    user_id = decode_access_token(session.access)
    assert all(t.revoked_at is not None for t in await committed_tokens(async_engine, user_id))
    async with async_engine.connect() as conn:
        stored = await conn.scalar(select(User.password_hash).where(User.id == user_id))
    from app.core.security import verify_password

    assert verify_password(stored, NEW_PASSWORD)


# --------------------------------------------------------------------------
# Concurrency and locks
# --------------------------------------------------------------------------


async def test_concurrent_refresh_with_same_token(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    user_id = decode_access_token(session.access)

    # Hold the user lock so both requests queue behind it, then release.
    async with async_engine.connect() as blocker:
        transaction = await blocker.begin()
        await blocker.execute(
            select(User.id).where(User.id == user_id).with_for_update(key_share=True)
        )
        tasks = [
            asyncio.create_task(
                call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
            )
            for _ in range(2)
        ]
        await wait_for_lock_waiters(async_engine, 2)
        await transaction.rollback()
        responses = await asyncio.gather(*tasks)

    assert sorted(r.status_code for r in responses) == [200, 401]
    tokens = await committed_tokens(async_engine, user_id)
    # One rotation only (no second branch), and the whole family is revoked,
    # including the token issued to the first request.
    assert len(tokens) == 2
    assert len({t.family_id for t in tokens}) == 1
    assert all(t.revoked_at is not None for t in tokens)


async def test_refresh_waits_for_deactivation_without_deadlock(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    user_id = decode_access_token(session.access)

    async with async_engine.connect() as admin:
        transaction = await admin.begin()
        # Deactivation takes the user lock first (same order as DEC-140).
        await admin.execute(update(User).where(User.id == user_id).values(is_active=False))
        task = asyncio.create_task(
            call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
        )
        await wait_for_lock_waiters(async_engine, 1)
        await admin.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=text("now()"))
        )
        await transaction.commit()
        response = await asyncio.wait_for(task, timeout=10)

    assert response.status_code == 401
    assert refresh_set_cookie(response) is None
    assert all(t.revoked_at is not None for t in await committed_tokens(async_engine, user_id))


async def test_concurrent_registration_with_same_email(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    client, users = committing_client
    email = users.new_email()

    # Another transaction inserts the same email and keeps it uncommitted:
    # the request passes the pre-check, then waits on the unique index.
    async with async_engine.connect() as other:
        transaction = await other.begin()
        await other.execute(
            insert(User).values(
                email=email, password_hash=hash_password(PASSWORD), full_name="Other"
            )
        )
        task = asyncio.create_task(call(client, "POST", "/register", json=register_body(email)))
        await wait_for_lock_waiters(async_engine, 1)
        await transaction.commit()
        response = await asyncio.wait_for(task, timeout=10)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert refresh_set_cookie(response) is None
    async with async_engine.connect() as conn:
        count = await conn.scalar(
            select(text("count(*)")).select_from(User).where(User.email == email)
        )
    assert count == 1


async def test_refresh_runs_in_read_committed(
    committing_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    seen: list[str] = []
    original = service.refresh_in_transaction

    async def spy(db: AsyncSession, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        seen.append(await db.scalar(text("SELECT current_setting('transaction_isolation')")))
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(service, "refresh_in_transaction", spy)
    response = await call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    assert response.status_code == 200
    assert seen == ["read committed"]


# --------------------------------------------------------------------------
# COMMIT failures (DEC-140: no success response, no cookie change)
# --------------------------------------------------------------------------


class SimulatedCommitError(Exception):
    pass


def _fail_commit(monkeypatch: pytest.MonkeyPatch, *, after_real_commit: bool) -> None:
    real_commit = AsyncSession.commit

    async def failing_commit(self: AsyncSession) -> None:
        if after_real_commit:
            await real_commit(self)  # committed, but the app never learns it
        raise SimulatedCommitError

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)


@pytest.mark.parametrize("after_real_commit", [False, True], ids=["before", "after"])
async def test_login_commit_failure(
    committing_client: Client,
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    after_real_commit: bool,
) -> None:
    client, users = committing_client
    email = users.new_email()
    session = await register(client, email)
    user_id = decode_access_token(session.access)

    _fail_commit(monkeypatch, after_real_commit=after_real_commit)
    response = await call(client, "POST", "/login", json={"email": email, "password": PASSWORD})
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert refresh_set_cookie(response) is None
    families = {t.family_id for t in await committed_tokens(async_engine, user_id)}
    # before: the new family was rolled back; after: it may exist (unknown result).
    assert len(families) == (2 if after_real_commit else 1)


@pytest.mark.parametrize("after_real_commit", [False, True], ids=["before", "after"])
async def test_logout_commit_failure_keeps_cookie(
    committing_client: Client,
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    after_real_commit: bool,
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    user_id = decode_access_token(session.access)

    _fail_commit(monkeypatch, after_real_commit=after_real_commit)
    response = await call(client, "POST", "/logout", refresh=session.refresh, csrf=True)
    monkeypatch.undo()

    assert response.status_code == 500
    assert refresh_set_cookie(response) is None  # cookie is not cleared
    revoked = [t.revoked_at is not None for t in await committed_tokens(async_engine, user_id)]
    assert revoked == [after_real_commit]


@pytest.mark.parametrize("after_real_commit", [False, True], ids=["before", "after"])
async def test_refresh_commit_failure_sends_no_new_cookie(
    committing_client: Client,
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    after_real_commit: bool,
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    user_id = decode_access_token(session.access)
    old_hash = hash_refresh_token(session.refresh)

    _fail_commit(monkeypatch, after_real_commit=after_real_commit)
    response = await call(client, "POST", "/refresh", refresh=session.refresh, csrf=True)
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert refresh_set_cookie(response) is None  # the new token never reaches the client
    tokens = {t.token_hash: t for t in await committed_tokens(async_engine, user_id)}
    if after_real_commit:
        # The rotation was committed although the app could not confirm it.
        assert len(tokens) == 2
        assert tokens[old_hash].revoked_at is not None
    else:
        assert list(tokens) == [old_hash]
        assert tokens[old_hash].revoked_at is None


@pytest.mark.parametrize("after_real_commit", [False, True], ids=["before", "after"])
async def test_password_change_commit_failure(
    committing_client: Client,
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    after_real_commit: bool,
) -> None:
    client, users = committing_client
    session = await register(client, users.new_email())
    user_id = decode_access_token(session.access)

    _fail_commit(monkeypatch, after_real_commit=after_real_commit)
    response = await call(
        client,
        "POST",
        "/password/change",
        access=session.access,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert refresh_set_cookie(response) is None  # cookie is not cleared, no 204
    async with async_engine.connect() as conn:
        stored_hash = await conn.scalar(select(User.password_hash).where(User.id == user_id))
    revoked = [t.revoked_at is not None for t in await committed_tokens(async_engine, user_id)]
    if after_real_commit:
        # Committed in the database, not confirmed to the client: no rollback claimed.
        assert verify_password(stored_hash, NEW_PASSWORD)
        assert revoked == [True]
    else:
        assert verify_password(stored_hash, PASSWORD)
        assert revoked == [False]


# --------------------------------------------------------------------------
# Login and concurrent deactivation / password change (DEC-143)
# --------------------------------------------------------------------------


async def _deactivate(engine: AsyncEngine, user_id: uuid.UUID) -> None:
    """Deactivation as DEC-140 orders it: user row first, then its tokens."""
    async with engine.begin() as conn:
        await conn.execute(update(User).where(User.id == user_id).values(is_active=False))
        await conn.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=text("now()"))
        )


async def test_login_waits_for_deactivation(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    """Deactivation holds the user lock first: login gets 401, no new family."""
    client, users = committing_client
    email = users.new_email()
    session = await register(client, email)
    user_id = decode_access_token(session.access)

    async with async_engine.connect() as admin:
        transaction = await admin.begin()
        await admin.execute(update(User).where(User.id == user_id).values(is_active=False))
        task = asyncio.create_task(
            call(client, "POST", "/login", json={"email": email, "password": PASSWORD})
        )
        await wait_for_lock_waiters(async_engine, 1)  # login waits for the user lock
        await admin.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=text("now()"))
        )
        await transaction.commit()
        response = await asyncio.wait_for(task, timeout=10)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert refresh_set_cookie(response) is None
    tokens = await committed_tokens(async_engine, user_id)
    assert len({t.family_id for t in tokens}) == 1  # only the registration family
    assert all(t.revoked_at is not None for t in tokens)


async def test_deactivation_waits_for_login(
    committing_client: Client, async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Login holds the user lock first: it succeeds, then the deactivation
    revokes every token, including the family login just created."""
    client, users = committing_client
    email = users.new_email()
    session = await register(client, email)
    user_id = decode_access_token(session.access)

    locked = asyncio.Event()
    proceed = asyncio.Event()
    original_create_family = service.create_family

    async def paused_create_family(db, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        locked.set()  # called only after login took the user lock
        await proceed.wait()
        return await original_create_family(db, *args, **kwargs)

    monkeypatch.setattr(service, "create_family", paused_create_family)
    login_task = asyncio.create_task(
        call(client, "POST", "/login", json={"email": email, "password": PASSWORD})
    )
    await asyncio.wait_for(locked.wait(), timeout=10)
    deactivation = asyncio.create_task(_deactivate(async_engine, user_id))
    await wait_for_lock_waiters(async_engine, 1)  # deactivation waits for login's lock
    proceed.set()
    response = await asyncio.wait_for(login_task, timeout=10)
    await asyncio.wait_for(deactivation, timeout=10)
    monkeypatch.undo()

    assert response.status_code == 200
    assert refresh_set_cookie(response) is not None
    tokens = await committed_tokens(async_engine, user_id)
    assert len({t.family_id for t in tokens}) == 2  # registration + login
    assert all(t.revoked_at is not None for t in tokens)
    async with async_engine.connect() as conn:
        assert await conn.scalar(select(User.is_active).where(User.id == user_id)) is False


async def test_login_rejects_password_changed_while_waiting_for_lock(
    committing_client: Client, async_engine: AsyncEngine
) -> None:
    """The hash verified before the lock must still be the stored one; a
    login with the old password never restores it through a rehash."""
    client, users = committing_client
    email = users.new_email()
    session = await register(client, email)
    user_id = decode_access_token(session.access)
    new_hash = hash_password(NEW_PASSWORD)

    async with async_engine.connect() as other:
        transaction = await other.begin()
        await other.execute(update(User).where(User.id == user_id).values(password_hash=new_hash))
        task = asyncio.create_task(
            call(client, "POST", "/login", json={"email": email, "password": PASSWORD})
        )
        await wait_for_lock_waiters(async_engine, 1)
        await transaction.commit()
        response = await asyncio.wait_for(task, timeout=10)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    async with async_engine.connect() as conn:
        assert await conn.scalar(select(User.password_hash).where(User.id == user_id)) == new_hash
    assert len({t.family_id for t in await committed_tokens(async_engine, user_id)}) == 1


# --------------------------------------------------------------------------
# committing_client teardown (DEC: cleanup and final check always run)
# --------------------------------------------------------------------------


async def test_teardown_runs_cleanup_and_check_when_dispose_fails(
    async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.conftest as conftest_module

    users = CommittedUsers()
    email = users.new_email()
    async with async_engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                email=email, password_hash=hash_password(PASSWORD), full_name="Teardown"
            )
        )
    before = {"users": 0, "refresh_tokens": 0, "user_roles": 0, "password_reset_tokens": 0}
    async with async_engine.connect() as conn:
        before["roles"] = await conn.scalar(select(text("count(*)")).select_from(text("roles")))

    class DisposeFailed(Exception):
        pass

    async def failing_dispose() -> None:
        raise DisposeFailed

    monkeypatch.setattr(conftest_module, "dispose_engine", failing_dispose)
    with pytest.raises(DisposeFailed):
        await conftest_module.finish_committing_client(async_engine, users, set(), before)
    monkeypatch.undo()

    async with async_engine.connect() as conn:
        assert await conn.scalar(select(text("count(*)")).select_from(User)) == 0


async def test_teardown_reports_dispose_error_and_leftovers_together(
    async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.conftest as conftest_module

    stray = CommittedUsers()  # created here but deliberately not passed to teardown
    email = stray.new_email()
    async with async_engine.begin() as conn:
        await conn.execute(
            insert(User).values(
                email=email, password_hash=hash_password(PASSWORD), full_name="Stray"
            )
        )
    before = {"users": 0, "refresh_tokens": 0, "user_roles": 0, "password_reset_tokens": 0}
    async with async_engine.connect() as conn:
        before["roles"] = await conn.scalar(select(text("count(*)")).select_from(text("roles")))

    class DisposeFailed(Exception):
        pass

    async def failing_dispose() -> None:
        raise DisposeFailed

    monkeypatch.setattr(conftest_module, "dispose_engine", failing_dispose)
    try:
        with pytest.raises(ExceptionGroup) as info:
            await conftest_module.finish_committing_client(
                async_engine, CommittedUsers(), set(), before
            )
        kinds = {type(exc) for exc in info.value.exceptions}
        assert kinds == {DisposeFailed, AssertionError}  # nothing hidden, check still ran
    finally:
        monkeypatch.undo()
        await conftest_module.finish_committing_client(async_engine, stray, set(), before)


# --------------------------------------------------------------------------
# Guard: ON DELETE actions the test cleanup relies on (read-only)
# --------------------------------------------------------------------------

_CASCADE_FROM_USERS = {
    "user_roles",
    "refresh_tokens",
    "password_reset_tokens",
    "addresses",
    "courier_profiles",
    "carts",
    "notifications",
    "telegram_links",
    "telegram_link_tokens",
    "telegram_outbox",
    "idempotency_keys",
}


async def test_user_foreign_keys_cascade_for_cleanup(async_engine: AsyncEngine) -> None:
    async with async_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text AS child,
                           a.attname AS column_name,
                           c.confdeltype AS action
                    FROM pg_constraint c
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                    WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass
                    """
                )
            )
        ).all()
    actions = {(row.child, row.column_name): row.action for row in rows}
    for table in _CASCADE_FROM_USERS:
        assert actions.get((table, "user_id")) == "c", f"{table}.user_id must be ON DELETE CASCADE"
    # Tables that block deleting a user: S3-B tests must never create rows there.
    restrict = {key for key, action in actions.items() if action in {"r", "a"}}
    assert restrict == {
        ("orders", "user_id"),
        ("cancellation_requests", "user_id"),
        ("courier_assignments", "courier_id"),
    }
