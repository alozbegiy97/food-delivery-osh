"""Seed CLI without committed data: arguments, configuration errors, lock.

Every subprocess gets DATABASE_URL explicitly: the unreachable address for
argument/configuration tests, TEST_DATABASE_URL (isolated `db-test`) for
the one test that connects. No test here commits anything.

The in-process tests at the end replace the engine and the seed function
with fakes: they never open a database connection.
"""

import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import OperationalError

from app.db.base import Base
from app.seeds import __main__ as cli
from app.seeds.common import SEED_ADVISORY_LOCK_KEY, SeedReport
from tests.conftest import (
    BACKEND_DIR,
    TEST_DATABASE_URL,
    UNREACHABLE_DATABASE_URL,
    verify_test_database,
)

BASE_TABLES = ["roles", "payment_methods", "restaurant_settings", "restaurant_working_hours"]


def _run_cli(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-m", "app.seeds", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _env(database_url: str) -> dict[str, str]:
    return {**os.environ, "DATABASE_URL": database_url}


def test_cli_requires_mode() -> None:
    result = _run_cli(env=_env(UNREACHABLE_DATABASE_URL))
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_cli_rejects_unknown_mode() -> None:
    result = _run_cli("nope", env=_env(UNREACHABLE_DATABASE_URL))
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_cli_help() -> None:
    result = _run_cli("--help", env=_env(UNREACHABLE_DATABASE_URL))
    assert result.returncode == 0
    assert "base" in result.stdout
    assert "demo" in result.stdout


def test_cli_unreachable_database_hides_details() -> None:
    result = _run_cli("base", env=_env(UNREACHABLE_DATABASE_URL))
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Seed прерван: ошибка БД" in result.stderr
    assert "Изменения не сохранены" in result.stderr
    for secret in (UNREACHABLE_DATABASE_URL, "127.0.0.1", "unreachable@", "password", "Traceback"):
        assert secret not in output, secret


def test_cli_without_database_url() -> None:
    env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    result = _run_cli("base", env=env)
    assert result.returncode == 1
    assert "Seed не запущен: ValidationError" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.db
def test_cli_lock_released_after_exit(sync_engine: Engine) -> None:
    verify_test_database()
    with sync_engine.connect() as conn:
        for name in BASE_TABLES:
            count = conn.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
            if count:
                pytest.fail(f"db-test must have an empty {name} table before this test")

    result = _run_cli("demo", env=_env(TEST_DATABASE_URL or ""))

    assert result.returncode == 1  # error kind 1: base missing, rolled back
    assert "требует выполненного base" in result.stderr
    with sync_engine.connect() as conn:
        acquired = conn.scalar(
            text("SELECT pg_try_advisory_xact_lock(CAST(:key AS bigint))"),
            {"key": SEED_ADVISORY_LOCK_KEY},
        )
        conn.rollback()
    assert acquired is True


# --- In-process tests with fakes (no database connection) -----------------------------


class _FakeConnection:
    async def scalar(self, _statement: Any) -> str:
        return "fake_db_test"


class _FakeTransaction:
    """Stands in for `engine.begin()`; records how the block was left."""

    def __init__(self, engine: _FakeEngine) -> None:
        self.engine = engine

    async def __aenter__(self) -> _FakeConnection:
        return _FakeConnection()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.engine.exit_exception = exc_type
        if exc_type is None and self.engine.commit_error is not None:
            raise self.engine.commit_error  # COMMIT itself fails
        return False  # never swallow exceptions, like SQLAlchemy


class _FakeEngine:
    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        dispose_error: BaseException | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.dispose_error = dispose_error
        self.exit_exception: Any = "block not entered"
        self.disposed = False

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def dispose(self) -> None:
        self.disposed = True
        if self.dispose_error is not None:
            raise self.dispose_error


def _install_fakes(monkeypatch: pytest.MonkeyPatch, engine: _FakeEngine, seed: Any) -> None:
    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(database_url="postgresql+psycopg://fake/x")
    )
    monkeypatch.setattr(cli, "create_async_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setitem(cli.MODES, "base", seed)


async def _successful_seed(_conn: Any) -> SeedReport:
    report = SeedReport()
    report.add("roles", 4, 0)
    return report


def test_keyboard_interrupt_during_seed_exits_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def interrupted_seed(_conn: Any) -> SeedReport:
        raise KeyboardInterrupt

    engine = _FakeEngine()
    _install_fakes(monkeypatch, engine, interrupted_seed)

    assert cli.main(["base"]) == 130

    stderr = capsys.readouterr().err
    assert "Seed прерван пользователем. Изменения не сохранены (rollback)." in stderr
    assert engine.exit_exception is KeyboardInterrupt  # left begin() with the exception
    assert engine.disposed is True


def test_keyboard_interrupt_after_commit_reports_saved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = _FakeEngine(dispose_error=KeyboardInterrupt())
    _install_fakes(monkeypatch, engine, _successful_seed)

    assert cli.main(["base"]) == 130

    stderr = capsys.readouterr().err
    assert "Seed прерван пользователем после фиксации: изменения сохранены." in stderr
    assert engine.exit_exception is None  # COMMIT path


def test_dispose_error_after_commit_keeps_exit_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = _FakeEngine(dispose_error=RuntimeError("dispose failed"))
    _install_fakes(monkeypatch, engine, _successful_seed)

    assert cli.main(["base"]) == 0

    captured = capsys.readouterr()
    assert "roles: создано 4, уже было 0" in captured.out
    assert "Готово. Изменения зафиксированы." in captured.out
    assert (
        "Предупреждение: Изменения зафиксированы. Закрытие соединений завершилось ошибкой "
        "RuntimeError." in captured.err
    )
    assert "не сохранены" not in captured.err
    assert "dispose failed" not in captured.out + captured.err
    assert engine.exit_exception is None
    assert engine.disposed is True


def test_commit_failure_reports_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commit_error = OperationalError("COMMIT", {}, Exception("connection lost: secret"))
    engine = _FakeEngine(commit_error=commit_error)
    _install_fakes(monkeypatch, engine, _successful_seed)

    assert cli.main(["base"]) == 1

    captured = capsys.readouterr()
    assert "Seed прерван: ошибка БД OperationalError." in captured.err
    assert "Результат фиксации неизвестен: ошибка произошла во время COMMIT." in captured.err
    assert "не сохранены" not in captured.err
    assert "Готово" not in captured.out
    assert "secret" not in captured.out + captured.err
    assert engine.disposed is True


def test_unexpected_error_exits_1_with_rollback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing_seed(_conn: Any) -> SeedReport:
        raise ValueError("internal detail: secret")

    engine = _FakeEngine()
    _install_fakes(monkeypatch, engine, failing_seed)

    assert cli.main(["base"]) == 1

    captured = capsys.readouterr()
    assert "Seed прерван: ValueError." in captured.err
    assert "Изменения не сохранены (rollback)." in captured.err
    assert "secret" not in captured.out + captured.err
    assert "Готово" not in captured.out
    assert engine.exit_exception is ValueError  # the error left begin() -> rollback
    assert engine.disposed is True
