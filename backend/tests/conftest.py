"""Test configuration.

Safety rule: tests never touch the main database. DATABASE_URL is always
replaced with TEST_DATABASE_URL (the isolated `db-test` service). Without
TEST_DATABASE_URL, tests marked `db` are skipped and DATABASE_URL points to
an unreachable address.
"""

import os
import secrets
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# Fixtures of the stage 6 tests (checkout, orders, addresses); loaded after
# this module, so the environment below is already prepared.
pytest_plugins = ["tests.orders_support"]

_ORIGINAL_DATABASE_URL = os.environ.get("DATABASE_URL")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://unreachable@127.0.0.1:1/unreachable"

if TEST_DATABASE_URL and TEST_DATABASE_URL == _ORIGINAL_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL (main database)", returncode=2)

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or UNREACHABLE_DATABASE_URL
# Auth settings for tests (DEC-140): a random per-run JWT secret (the real
# one from `.env` is never used by tests), the ASGI test origin for CSRF and
# light Argon2 parameters so password hashing stays fast.
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["CSRF_TRUSTED_ORIGINS"] = "http://test"
os.environ["ARGON2_TIME_COST"] = "1"
os.environ["ARGON2_MEMORY_COST_KIB"] = "1024"
os.environ["ARGON2_PARALLELISM"] = "1"
# Rate limits are off by default in tests; test_rate_limit.py enables them.
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Telegram is disabled unless a test sets its own throw-away bot token; a
# real token from the environment is never used by tests (DEC-154 п. 8).
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
# Uploaded images go to a throw-away directory, never to the media volume.
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="media-test-")

BACKEND_DIR = Path(__file__).resolve().parent.parent

import uuid  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402  - environment must be prepared before app imports
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import Engine, create_engine, delete, func, or_, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

# Register every ORM model before any test runs: relationships declared by
# class name (e.g. Order.payments -> "Payment") are resolved only when all
# modules are imported, so a single test file must not depend on import order.
import app.db.models_registry  # noqa: E402, F401
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_db_engine, dispose_engine, get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.notifications.models import TelegramLink  # noqa: E402
from app.modules.users.enums import RoleName  # noqa: E402
from app.modules.users.models import (  # noqa: E402
    PasswordResetToken,
    RefreshToken,
    Role,
    User,
    UserRole,
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip_db = pytest.mark.skip(reason="TEST_DATABASE_URL is not set (isolated test DB required)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


def verify_test_database() -> str:
    """Fail hard unless TEST_DATABASE_URL points to the isolated test database.

    Checks the configured URL and the database the server actually reports,
    so destructive operations (downgrade, data changes) can never reach the
    main database.
    """
    import psycopg

    assert TEST_DATABASE_URL, "TEST_DATABASE_URL is not set"
    url = urlsplit(sync_database_url())
    expected_db = url.path.lstrip("/")
    problems = []
    if _ORIGINAL_DATABASE_URL and TEST_DATABASE_URL == _ORIGINAL_DATABASE_URL:
        problems.append("TEST_DATABASE_URL equals DATABASE_URL")
    if not expected_db.endswith("_test"):
        problems.append(f"database name {expected_db!r} does not end with '_test'")
    if _ORIGINAL_DATABASE_URL:
        main = urlsplit(_ORIGINAL_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1))
        if (main.hostname, main.port, main.path) == (url.hostname, url.port, url.path):
            problems.append("test database host/port/name equal the main database")
    with psycopg.connect(sync_database_url()) as conn:
        actual_db = conn.execute("SELECT current_database()").fetchone()[0]
    if actual_db != expected_db:
        problems.append(f"server reports database {actual_db!r}, expected {expected_db!r}")
    if problems:
        pytest.exit("Refusing to touch the database: " + "; ".join(problems), returncode=2)
    return f"{url.hostname}:{url.port}/{actual_db}"


def run_alembic(*args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    """Run the Alembic CLI against the verified test database in a subprocess.

    With `expect_success=False` the command must fail (a refused migration).
    """
    verify_test_database()
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL or ""}
    result = subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0, result.stdout
    return result


def sync_database_url() -> str:
    assert TEST_DATABASE_URL
    return TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def app() -> FastAPI:
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    await dispose_engine()


@pytest.fixture(scope="session")
def migrated_test_db() -> None:
    run_alembic("upgrade", "head")


@pytest.fixture(scope="session")
def sync_engine(migrated_test_db: None) -> Iterator[Engine]:
    """Synchronous engine on the verified, migrated test database."""
    verify_test_database()
    engine = create_engine(TEST_DATABASE_URL or "", poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine: Engine) -> Iterator[Session]:
    """ORM session inside an outer transaction that is always rolled back.

    `session.begin_nested()` / failed flushes only roll back to a savepoint,
    so no test data ever persists in the test database.
    """
    with sync_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture(scope="session")
async def async_engine(migrated_test_db: None) -> AsyncIterator[AsyncEngine]:
    """Async engine on the verified, migrated test database.

    Built like the application engine (explicit READ COMMITTED, DEC-140).
    """
    verify_test_database()
    engine = create_db_engine(TEST_DATABASE_URL or "", poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def seed_conn(async_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Async connection inside an outer transaction that is always rolled back.

    Seed functions never commit, so everything they write (and the advisory
    lock they take) disappears with this rollback.
    """
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


# --------------------------------------------------------------------------
# HTTP clients for API tests (S3-B)
#
# Isolation: pytest runs tests one after another in one process and one
# event loop (no pytest-xdist; asyncio loop scope "session"). The global
# application engine is therefore never shared by two tests at the same
# time; committing_client additionally refuses to run under xdist and
# disposes the global engine before and after the test.
# --------------------------------------------------------------------------

_NO_OVERRIDE = object()
# telegram_links rows go with their users (ON DELETE CASCADE); counting
# them proves the Mini App tests leave nothing behind either.
_AUTH_TABLES = (User, RefreshToken, UserRole, PasswordResetToken, TelegramLink)


@contextmanager
def override_dependency(app: FastAPI, dependency: Any, replacement: Any) -> Iterator[None]:
    """Override one dependency and restore exactly the previous state."""
    previous = app.dependency_overrides.get(dependency, _NO_OVERRIDE)
    app.dependency_overrides[dependency] = replacement
    try:
        yield
    finally:
        if previous is _NO_OVERRIDE:
            app.dependency_overrides.pop(dependency, None)
        else:
            app.dependency_overrides[dependency] = previous


@pytest.fixture
async def api_conn(async_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One outer transaction per test; always rolled back."""
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest.fixture
async def api_client(app: FastAPI, api_conn: AsyncConnection) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client whose requests run inside the test's outer transaction.

    Each request gets its own AsyncSession bound to `api_conn` with
    join_transaction_mode="create_savepoint": a service-level commit()
    only releases a SAVEPOINT; nothing is visible to other connections and
    everything disappears with the final rollback. Requests must be
    sequential (one connection). Not for visibility, lock or concurrency
    tests: use committing_client.
    """

    async def _session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=api_conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session:
            yield session

    with override_dependency(app, get_session, _session):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@dataclass
class CommittedUsers:
    """Users created through committing_client; removed after the test."""

    emails: set[str] = field(default_factory=set)
    ids: set[uuid.UUID] = field(default_factory=set)

    def new_email(self) -> str:
        # example.com: email-validator rejects special-use domains such as .test
        email = f"s3b-{uuid.uuid4().hex}@example.com"
        self.emails.add(email)
        return email

    def track(self, user_id: uuid.UUID) -> None:
        """Register a user created without a known email (K2-B later)."""
        self.ids.add(user_id)


async def _row_counts(engine: AsyncEngine) -> dict[str, int]:
    """Counts on a fresh connection: only committed data is visible."""
    async with engine.connect() as connection:
        return {
            model.__tablename__: int(
                await connection.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (*_AUTH_TABLES, Role)
        }


async def _delete_committed(
    engine: AsyncEngine, users: CommittedUsers, role_ids: set[uuid.UUID]
) -> None:
    """Delete test users (dependent rows go by ON DELETE CASCADE) and the
    roles this fixture created, on a separate connection of the test engine."""
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        if users.ids or users.emails:
            await connection.execute(
                delete(User).where(
                    or_(User.id.in_(users.ids), func.lower(User.email).in_(users.emails))
                )
            )
        if role_ids:
            await connection.execute(delete(Role).where(Role.id.in_(role_ids)))


@pytest.fixture
async def committing_client(
    app: FastAPI, async_engine: AsyncEngine
) -> AsyncIterator[tuple[httpx.AsyncClient, CommittedUsers]]:
    """HTTP client with real COMMITs through the application's global engine.

    Requests use the normal get_session -> get_engine() (DATABASE_URL points
    to the verified test database; READ COMMITTED, DEC-140). Missing roles
    are created here and removed again. Cleanup always runs (finally), after
    the application engine is disposed, on a separate connection.
    """
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail("committing_client must not run in parallel workers")
    verify_test_database()
    if get_session in app.dependency_overrides:
        pytest.fail("committing_client needs the real get_session (no override)")

    before = await _row_counts(async_engine)
    leftovers = {name: n for name, n in before.items() if name != "roles" and n}
    if leftovers:
        pytest.fail(f"db-test is not clean before the test: {leftovers}")

    users = CommittedUsers()
    created_role_ids: set[uuid.UUID] = set()
    try:
        await dispose_engine()  # the global engine is created fresh for this test
        async with async_engine.begin() as connection:
            created_role_ids = set(
                (
                    await connection.scalars(
                        pg_insert(Role)
                        .values([{"name": name.value} for name in RoleName])
                        .on_conflict_do_nothing(index_elements=["name"])
                        .returning(Role.id)
                    )
                ).all()
            )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, users
    finally:
        await finish_committing_client(async_engine, users, created_role_ids, before)


async def finish_committing_client(
    engine: AsyncEngine,
    users: CommittedUsers,
    created_role_ids: set[uuid.UUID],
    before: dict[str, int],
) -> None:
    """Teardown of committing_client.

    Each step runs even if an earlier one failed: dispose the app engine,
    delete this test's rows, check that the auth tables are clean. Failures
    are collected and re-raised afterwards (one error as is, several as an
    ExceptionGroup), so nothing is hidden and no step is skipped.
    """
    failures: list[Exception] = []
    try:
        await dispose_engine()  # no pooled app connection may hold locks
    except Exception as exc:
        failures.append(exc)
    try:
        await _delete_committed(engine, users, created_role_ids)
    except Exception as exc:
        failures.append(exc)
    try:
        after = await _row_counts(engine)
        problems = {name: n for name, n in after.items() if name != "roles" and n}
        if after["roles"] != before["roles"]:
            problems["roles"] = after["roles"]
        if problems:
            failures.append(AssertionError(f"committing_client left rows in db-test: {problems}"))
    except Exception as exc:
        failures.append(exc)
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise ExceptionGroup("committing_client teardown failed", failures)
