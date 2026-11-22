"""Refresh sessions service (DEC-65, DEC-110, DEC-140; package DB-B).

Three groups:

- pure functions (no database);
- single-transaction scenarios inside `seed_conn` (always rolled back);
- concurrency scenarios with real COMMITs on the isolated `db-test` only.
  They create users `dbb-<uuid>@example.test`, use `lock_timeout` 5 s and
  `statement_timeout` 15 s, wait for lock waits via `pg_stat_activity`
  (not fixed sleeps) and delete exactly their own users in `finally`
  (refresh tokens go by ON DELETE CASCADE). The module checks that the
  test database has no users before and after it runs.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker

from app.modules.auth.refresh_sessions import (
    MAX_REFRESH_TOKEN_LENGTH,
    RefreshOutcome,
    RefreshRotationConflict,
    RefreshStatus,
    create_family,
    decide_refresh,
    hash_refresh_token,
    lock_user,
    mark_rotated,
    new_refresh_token,
    refresh_in_transaction,
    revoke_all_for_user,
    revoke_family,
)
from app.modules.users.models import RefreshToken, User
from tests.conftest import verify_test_database

TTL = timedelta(days=30)
WAIT_TIMEOUT = 60
_tokens = RefreshToken.__table__
_users = User.__table__


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Pure functions
# --------------------------------------------------------------------------


def test_new_refresh_token_is_32_bytes_base64url() -> None:
    tokens = {new_refresh_token() for _ in range(50)}
    assert len(tokens) == 50
    for token in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def test_hash_refresh_token_is_sha256_hex() -> None:
    assert hash_refresh_token("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


@pytest.mark.parametrize(
    ("found", "active", "revoked", "expired", "expected"),
    [
        (False, False, True, True, RefreshStatus.UNKNOWN),
        (True, False, True, True, RefreshStatus.INACTIVE),
        (True, False, False, False, RefreshStatus.INACTIVE),
        (True, True, True, True, RefreshStatus.REUSED),
        (True, True, False, True, RefreshStatus.EXPIRED),
        (True, True, False, False, RefreshStatus.OK),
    ],
)
def test_decide_refresh_order(
    found: bool, active: bool, revoked: bool, expired: bool, expected: RefreshStatus
) -> None:
    status = decide_refresh(
        token_found=found, owner_active=active, revoked=revoked, expired=expired
    )
    assert status is expected


def test_outcome_repr_hides_new_token() -> None:
    outcome = RefreshOutcome(RefreshStatus.OK, new_token="secret-value")
    assert "secret-value" not in repr(outcome)


async def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await refresh_in_transaction(
            None,  # type: ignore[arg-type]  # rejected before any database access
            "x",
            now=datetime(2026, 1, 1),  # noqa: DTZ001 - deliberately naive
            ttl=TTL,
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _insert_user(conn: AsyncConnection, *, is_active: bool = True) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        insert(_users).values(
            id=user_id,
            email=f"dbb-{user_id}@example.test",
            password_hash="not-a-real-hash",  # noqa: S106 - test data, never verified
            full_name="DB-B test user",
            is_active=is_active,
        )
    )
    return user_id


async def _token_rows(conn: AsyncConnection, user_id: uuid.UUID) -> list:
    result = await conn.execute(
        select(_tokens).where(_tokens.c.user_id == user_id).order_by(_tokens.c.created_at)
    )
    return list(result.all())


async def _active_hashes(conn: AsyncConnection, user_id: uuid.UUID) -> set[str]:
    result = await conn.execute(
        select(_tokens.c.token_hash).where(
            _tokens.c.user_id == user_id, _tokens.c.revoked_at.is_(None)
        )
    )
    return set(result.scalars())


# --------------------------------------------------------------------------
# Single transaction (seed_conn, always rolled back)
# --------------------------------------------------------------------------


@pytest.mark.db
async def test_refresh_transaction_runs_read_committed(seed_conn: AsyncConnection) -> None:
    level = (await seed_conn.execute(text("SHOW transaction_isolation"))).scalar_one()
    assert level == "read committed"


@pytest.mark.db
async def test_create_family_stores_only_hash(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    family_id, raw = await create_family(seed_conn, user_id, now=now, ttl=TTL)

    rows = await _token_rows(seed_conn, user_id)
    assert len(rows) == 1
    assert rows[0].family_id == family_id
    assert rows[0].token_hash == hash_refresh_token(raw)
    assert rows[0].token_hash != raw
    assert rows[0].expires_at == now + TTL
    assert rows[0].revoked_at is None


@pytest.mark.db
async def test_successful_rotation(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    family_id, raw = await create_family(seed_conn, user_id, now=now, ttl=TTL)

    outcome = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)

    assert outcome.status is RefreshStatus.OK
    assert outcome.user_id == user_id
    assert outcome.family_id == family_id
    assert outcome.new_token and outcome.new_token != raw
    old, new = await _token_rows(seed_conn, user_id)
    assert old.token_hash == hash_refresh_token(raw)
    assert old.revoked_at == now
    assert old.replaced_by_id == new.id
    assert new.token_hash == hash_refresh_token(outcome.new_token)
    assert new.family_id == family_id
    assert new.revoked_at is None
    assert new.expires_at == now + TTL


@pytest.mark.db
async def test_reused_token_revokes_whole_family_only(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    _, raw = await create_family(seed_conn, user_id, now=now, ttl=TTL)
    _, other_family_raw = await create_family(seed_conn, user_id, now=now, ttl=TTL)
    first = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)
    assert first.status is RefreshStatus.OK

    second = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)

    assert second.status is RefreshStatus.REUSED
    assert second.new_token is None
    # The token issued by the first refresh is revoked too; the other family
    # of the same user stays active.
    assert await _active_hashes(seed_conn, user_id) == {hash_refresh_token(other_family_raw)}
    assert len(await _token_rows(seed_conn, user_id)) == 3


@pytest.mark.db
@pytest.mark.parametrize("raw", [None, "", "x" * (MAX_REFRESH_TOKEN_LENGTH + 1)])
async def test_missing_or_oversized_token_is_unknown(
    seed_conn: AsyncConnection, raw: str | None
) -> None:
    outcome = await refresh_in_transaction(seed_conn, raw, now=_now(), ttl=TTL)
    assert outcome == RefreshOutcome(RefreshStatus.UNKNOWN)


@pytest.mark.db
async def test_unknown_token_writes_nothing(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    await create_family(seed_conn, user_id, now=_now(), ttl=TTL)
    before = await _token_rows(seed_conn, user_id)

    outcome = await refresh_in_transaction(seed_conn, new_refresh_token(), now=_now(), ttl=TTL)

    assert outcome == RefreshOutcome(RefreshStatus.UNKNOWN)
    assert await _token_rows(seed_conn, user_id) == before


@pytest.mark.db
async def test_inactive_owner_revokes_all_sessions(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    other_user = await _insert_user(seed_conn)
    now = _now()
    # Presented token is expired: the inactive owner check comes first.
    _, raw = await create_family(seed_conn, user_id, now=now - TTL, ttl=TTL)
    await create_family(seed_conn, user_id, now=now, ttl=TTL)
    _, other_raw = await create_family(seed_conn, other_user, now=now, ttl=TTL)
    await seed_conn.execute(update(_users).where(_users.c.id == user_id).values(is_active=False))

    outcome = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)

    assert outcome.status is RefreshStatus.INACTIVE
    assert outcome.new_token is None
    assert await _active_hashes(seed_conn, user_id) == set()
    assert await _active_hashes(seed_conn, other_user) == {hash_refresh_token(other_raw)}


@pytest.mark.db
async def test_revoked_check_comes_before_expired(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    family_id, raw = await create_family(seed_conn, user_id, now=now - TTL, ttl=TTL)
    await seed_conn.execute(
        update(_tokens).where(_tokens.c.family_id == family_id).values(revoked_at=now)
    )
    outcome = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)
    assert outcome.status is RefreshStatus.REUSED


@pytest.mark.db
@pytest.mark.parametrize("age", [TTL, TTL + timedelta(seconds=1)])
async def test_expired_token_revokes_nothing(seed_conn: AsyncConnection, age: timedelta) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    _, raw = await create_family(seed_conn, user_id, now=now - age, ttl=TTL)

    outcome = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)

    assert outcome.status is RefreshStatus.EXPIRED
    assert outcome.new_token is None
    assert await _active_hashes(seed_conn, user_id) == {hash_refresh_token(raw)}
    assert len(await _token_rows(seed_conn, user_id)) == 1


@pytest.mark.db
async def test_token_valid_one_second_before_expiry(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    _, raw = await create_family(seed_conn, user_id, now=now - TTL + timedelta(seconds=1), ttl=TTL)
    outcome = await refresh_in_transaction(seed_conn, raw, now=now, ttl=TTL)
    assert outcome.status is RefreshStatus.OK


@pytest.mark.db
async def test_mark_rotated_requires_exactly_one_active_row(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    family_id, _ = await create_family(seed_conn, user_id, now=now, ttl=TTL)
    (row,) = await _token_rows(seed_conn, user_id)
    await revoke_family(seed_conn, family_id, now=now)

    with pytest.raises(RefreshRotationConflict):
        await mark_rotated(seed_conn, row.id, row.id, now=now)


@pytest.mark.db
async def test_revoke_helpers_return_counts(seed_conn: AsyncConnection) -> None:
    user_id = await _insert_user(seed_conn)
    now = _now()
    family_id, _ = await create_family(seed_conn, user_id, now=now, ttl=TTL)
    await create_family(seed_conn, user_id, now=now, ttl=TTL)

    assert await lock_user(seed_conn, user_id) is True
    assert await lock_user(seed_conn, uuid.uuid4()) is None
    assert await revoke_family(seed_conn, family_id, now=now) == 1
    assert await revoke_family(seed_conn, family_id, now=now) == 0
    assert await revoke_all_for_user(seed_conn, user_id, now=now) == 1
    assert await revoke_all_for_user(seed_conn, user_id, now=now) == 0


# --------------------------------------------------------------------------
# Concurrency with real COMMITs (db-test only)
# --------------------------------------------------------------------------


async def _count_users(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(_users))).scalar_one()


@pytest.fixture(scope="module")
async def clean_db_check(async_engine: AsyncEngine) -> AsyncIterator[None]:
    verify_test_database()
    assert await _count_users(async_engine) == 0, "db-test must have no users before DB-B tests"
    yield
    assert await _count_users(async_engine) == 0, "DB-B tests left users in db-test"


@pytest.fixture
async def committed_user(
    async_engine: AsyncEngine, clean_db_check: None
) -> AsyncIterator[Callable[[], Awaitable[uuid.UUID]]]:
    """Factory of committed users; deletes exactly these users afterwards."""
    created: list[uuid.UUID] = []

    async def make() -> uuid.UUID:
        async with async_engine.begin() as conn:
            user_id = await _insert_user(conn)
        created.append(user_id)
        return user_id

    try:
        yield make
    finally:
        if created:
            async with async_engine.begin() as conn:
                result = await conn.execute(delete(_users).where(_users.c.id.in_(created)))
            assert result.rowcount == len(created)


async def _prepare(conn: AsyncConnection) -> int:
    """Set safety timeouts and return the backend pid of this connection."""
    await conn.execute(text("SET lock_timeout = '5s'"))
    await conn.execute(text("SET statement_timeout = '15s'"))
    return (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def _wait_until_blocked(engine: AsyncEngine, pid: int) -> None:
    """Wait until backend `pid` waits for a lock (pg_stat_activity)."""
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        async with engine.connect() as conn:
            wait_type = (
                await conn.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pid},
                )
            ).scalar_one_or_none()
        if wait_type == "Lock":
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"backend {pid} did not start waiting for a lock")
        await asyncio.sleep(0.02)


async def _new_family(engine: AsyncEngine, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    async with engine.begin() as conn:
        return await create_family(conn, user_id, now=_now(), ttl=TTL)


@pytest.mark.db
async def test_concurrent_refresh_with_same_token(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    user_id = await committed_user()
    family_id, raw = await _new_family(async_engine, user_id)

    async with async_engine.connect() as conn_a, async_engine.connect() as conn_b:
        await _prepare(conn_a)
        pid_b = await _prepare(conn_b)
        first = await refresh_in_transaction(conn_a, raw, now=_now(), ttl=TTL)
        assert first.status is RefreshStatus.OK

        second_task = asyncio.create_task(refresh_in_transaction(conn_b, raw, now=_now(), ttl=TTL))
        await _wait_until_blocked(async_engine, pid_b)
        await conn_a.commit()
        second = await asyncio.wait_for(second_task, WAIT_TIMEOUT)
        await conn_b.commit()

    assert second.status is RefreshStatus.REUSED
    assert second.family_id == family_id
    # Seen from a third connection after both COMMITs: no valid branch left.
    async with async_engine.connect() as check:
        rows = await _token_rows(check, user_id)
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)


@pytest.mark.db
async def test_revoke_all_waits_for_rotation_without_deadlock(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    """Password change / admin revoke running next to a refresh: both take
    the users row first, so the second one waits and then revokes the token
    issued by the refresh as well."""
    user_id = await committed_user()
    _, raw = await _new_family(async_engine, user_id)

    async def revoke_all(conn: AsyncConnection) -> int:
        assert await lock_user(conn, user_id) is True
        return await revoke_all_for_user(conn, user_id, now=_now())

    async with async_engine.connect() as conn_a, async_engine.connect() as conn_b:
        await _prepare(conn_a)
        pid_b = await _prepare(conn_b)
        rotated = await refresh_in_transaction(conn_a, raw, now=_now(), ttl=TTL)
        assert rotated.status is RefreshStatus.OK

        revoke_task = asyncio.create_task(revoke_all(conn_b))
        await _wait_until_blocked(async_engine, pid_b)
        await conn_a.commit()
        revoked = await asyncio.wait_for(revoke_task, WAIT_TIMEOUT)
        await conn_b.commit()

    assert revoked == 1  # the new token from the rotation
    async with async_engine.connect() as check:
        assert await _active_hashes(check, user_id) == set()


@pytest.mark.db
async def test_deactivation_seen_by_waiting_refresh_not_identity_map(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    user_id = await committed_user()
    _, raw = await _new_family(async_engine, user_id)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async with async_engine.connect() as conn_a, factory() as session_b:
        await _prepare(conn_a)
        pid_b = (await session_b.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await session_b.execute(text("SET lock_timeout = '5s'"))
        # Session B has the user in its identity map as active.
        stale_user = await session_b.get(User, user_id)
        assert stale_user is not None and stale_user.is_active is True

        # A deactivates the user (and revokes sessions) but has not committed.
        assert await lock_user(conn_a, user_id) is True
        await conn_a.execute(update(_users).where(_users.c.id == user_id).values(is_active=False))
        await revoke_all_for_user(conn_a, user_id, now=_now())

        refresh_task = asyncio.create_task(
            refresh_in_transaction(session_b, raw, now=_now(), ttl=TTL)
        )
        await _wait_until_blocked(async_engine, pid_b)
        await conn_a.commit()
        outcome = await asyncio.wait_for(refresh_task, WAIT_TIMEOUT)
        # The identity map still says "active"; the service did not use it.
        assert stale_user.is_active is True
        await session_b.commit()

    assert outcome.status is RefreshStatus.INACTIVE
    async with async_engine.connect() as check:
        assert await _active_hashes(check, user_id) == set()
        assert len(await _token_rows(check, user_id)) == 1


@pytest.mark.db
async def test_committed_revocation_is_visible_to_other_connections(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    user_id = await committed_user()
    _, raw = await _new_family(async_engine, user_id)
    async with async_engine.begin() as conn:
        assert (await refresh_in_transaction(conn, raw, now=_now(), ttl=TTL)).status is (
            RefreshStatus.OK
        )

    async with async_engine.connect() as observer:
        await _prepare(observer)
        async with async_engine.begin() as conn:
            reuse = await refresh_in_transaction(conn, raw, now=_now(), ttl=TTL)
            # Not committed yet: the observer still sees one active token.
            assert len(await _active_hashes(observer, user_id)) == 1
            await observer.rollback()
        assert reuse.status is RefreshStatus.REUSED
        # After COMMIT the revocation is visible to the other connection.
        assert await _active_hashes(observer, user_id) == set()


@pytest.mark.db
async def test_exception_rolls_back_rotation(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    user_id = await committed_user()
    _, raw = await _new_family(async_engine, user_id)

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        async with async_engine.begin() as conn:
            outcome = await refresh_in_transaction(conn, raw, now=_now(), ttl=TTL)
            assert outcome.status is RefreshStatus.OK
            raise Boom

    async with async_engine.connect() as check:
        assert await _active_hashes(check, user_id) == {hash_refresh_token(raw)}
        assert len(await _token_rows(check, user_id)) == 1


@pytest.mark.db
async def test_user_lock_is_no_key_update(
    async_engine: AsyncEngine, committed_user: Callable[[], Awaitable[uuid.UUID]]
) -> None:
    """`FOR NO KEY UPDATE` (not `FOR UPDATE`): while the users row is locked,
    another transaction can still insert a row referencing it (the FK check
    takes `FOR KEY SHARE`), so unrelated inserts are not serialized."""
    user_id = await committed_user()
    async with async_engine.connect() as conn_a, async_engine.connect() as conn_b:
        await _prepare(conn_a)
        await _prepare(conn_b)
        await conn_b.execute(text("SET lock_timeout = '1s'"))
        assert await lock_user(conn_a, user_id) is True
        await create_family(conn_b, user_id, now=_now(), ttl=TTL)
        await conn_b.rollback()
        await conn_a.rollback()
