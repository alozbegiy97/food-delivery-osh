"""First administrator: `python -m app.cli create-admin` (DEC-88, DEC-113)."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.cli import __main__ as cli
from app.cli.create_admin import CreateAdminError, create_first_admin
from app.core.security import verify_password
from app.modules.users.enums import RoleName
from app.modules.users.models import Role, User, UserRole
from tests.auth_http import PASSWORD, wait_for_lock_waiters

pytestmark = pytest.mark.db

EMAIL = "admin@example.com"


async def _roles(conn: AsyncConnection) -> dict[str, uuid.UUID]:
    rows = await conn.execute(
        insert(Role).values([{"name": n.value} for n in RoleName]).returning(Role.name, Role.id)
    )
    return dict(rows.all())


async def test_creates_admin_only_with_admin_role(seed_conn: AsyncConnection) -> None:
    roles = await _roles(seed_conn)
    user_id = await create_first_admin(
        seed_conn, email=" Admin@Example.com ", full_name=" Главный ", password=PASSWORD
    )
    row = (
        await seed_conn.execute(
            select(User.email, User.full_name, User.password_hash, User.must_change_password).where(
                User.id == user_id
            )
        )
    ).one()
    assert (row.email, row.full_name, row.must_change_password) == (EMAIL, "Главный", False)
    assert row.password_hash.startswith("$argon2id$") and verify_password(
        row.password_hash, PASSWORD
    )
    user_roles = (
        await seed_conn.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id))
    ).all()
    assert user_roles == [roles["admin"]]


async def test_second_admin_is_refused(seed_conn: AsyncConnection) -> None:
    await _roles(seed_conn)
    await create_first_admin(seed_conn, email=EMAIL, full_name="A", password=PASSWORD)
    with pytest.raises(CreateAdminError, match="уже существует"):
        await create_first_admin(seed_conn, email="b@example.com", full_name="B", password=PASSWORD)


async def test_refusals(seed_conn: AsyncConnection) -> None:
    with pytest.raises(CreateAdminError, match="seeds base"):
        await create_first_admin(seed_conn, email=EMAIL, full_name="A", password=PASSWORD)
    roles = await _roles(seed_conn)
    customer = await seed_conn.scalar(
        insert(User).values(email=EMAIL, password_hash="x", full_name="Customer").returning(User.id)
    )
    await seed_conn.execute(insert(UserRole).values(user_id=customer, role_id=roles["customer"]))
    with pytest.raises(CreateAdminError, match="email уже существует"):
        await create_first_admin(seed_conn, email=EMAIL, full_name="A", password=PASSWORD)


@pytest.mark.parametrize(
    ("email", "full_name", "password"),
    [
        ("bad", "A", PASSWORD),
        (EMAIL, "  ", PASSWORD),
        (EMAIL, "A", "short1"),
        (EMAIL, "A", "lettersonly"),
    ],
)
async def test_invalid_input(
    seed_conn: AsyncConnection, email: str, full_name: str, password: str
) -> None:
    from pydantic import ValidationError

    await _roles(seed_conn)
    with pytest.raises(ValidationError) as info:
        await create_first_admin(seed_conn, email=email, full_name=full_name, password=password)
    assert password not in str(info.value)


async def test_parallel_runs_create_one_admin(async_engine: AsyncEngine) -> None:
    """Two runs at once: the second waits for the advisory lock, then refuses."""
    async with async_engine.begin() as conn:
        role_ids = list((await _roles(conn)).values())
    try:
        async with async_engine.connect() as first:
            tx = await first.begin()
            await create_first_admin(first, email=EMAIL, full_name="First", password=PASSWORD)

            async def second_run() -> None:
                async with async_engine.begin() as second:
                    await create_first_admin(
                        second, email="second@example.com", full_name="Second", password=PASSWORD
                    )

            task = asyncio.create_task(second_run())
            await wait_for_lock_waiters(async_engine, 1)
            await tx.commit()
            with pytest.raises(CreateAdminError):
                await asyncio.wait_for(task, timeout=10)
        async with async_engine.connect() as conn:
            assert await conn.scalar(select(func.count()).select_from(User)) == 1
    finally:
        async with async_engine.begin() as conn:
            await conn.execute(delete(User))
            await conn.execute(delete(Role).where(Role.id.in_(role_ids)))


def test_cli_password_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    answers = iter(["Admin", EMAIL])
    passwords = iter([PASSWORD, "different1"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(passwords))
    assert cli.main(["create-admin"]) == cli.EXIT_ERROR
    assert "не совпадают" in capsys.readouterr().err


def test_cli_creates_admin_in_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """End to end through the real command, committing to db-test; cleaned up after.

    The command runs its own event loop (`asyncio.run`), so preparation and
    cleanup use a separate loop with their own engine.
    """
    from sqlalchemy.pool import NullPool

    from app.db.session import create_db_engine
    from tests.conftest import TEST_DATABASE_URL, verify_test_database

    verify_test_database()

    async def prepare() -> list[uuid.UUID]:
        engine = create_db_engine(TEST_DATABASE_URL or "", poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return list((await _roles(conn)).values())
        finally:
            await engine.dispose()

    async def count_admins() -> int:
        engine = create_db_engine(TEST_DATABASE_URL or "", poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return int(
                    await conn.scalar(
                        select(func.count())
                        .select_from(UserRole)
                        .join(Role, Role.id == UserRole.role_id)
                        .where(Role.name == "admin")
                    )
                    or 0
                )
        finally:
            await engine.dispose()

    async def cleanup(role_ids: list[uuid.UUID]) -> None:
        engine = create_db_engine(TEST_DATABASE_URL or "", poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(delete(User).where(User.email == EMAIL))
                await conn.execute(delete(Role).where(Role.id.in_(role_ids)))
        finally:
            await engine.dispose()

    role_ids = asyncio.run(prepare())
    try:
        answers = iter(["Главный админ", "  Admin@Example.com "])
        passwords = iter([PASSWORD, PASSWORD])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
        monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(passwords))
        assert cli.main(["create-admin"]) == cli.EXIT_OK
        output = capsys.readouterr()
        assert f"Администратор создан: {EMAIL}" in output.out
        assert PASSWORD not in output.out + output.err
        assert asyncio.run(count_admins()) == 1

        answers = iter(["Второй", "second@example.com"])
        passwords = iter([PASSWORD, PASSWORD])
        assert cli.main(["create-admin"]) == cli.EXIT_ERROR
        assert "уже существует" in capsys.readouterr().err
    finally:
        asyncio.run(cleanup(role_ids))
