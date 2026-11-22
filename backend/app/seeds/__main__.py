"""Seed CLI: `python -m app.seeds base|demo` (DEC-117, DEC-136…DEC-139).

One mode runs in one transaction (`engine.begin()`): COMMIT only on a
normal exit of the block, ROLLBACK on any exception. Exceptions are never
caught inside the transaction block; they are handled outside it.

Exit codes:
- 0: success, changes committed (also when closing connections fails
  after the commit: a warning is printed);
- 1: seed error (DEC-136, DEC-137, DEC-139), database error or any other
  runtime error; changes are rolled back, or the COMMIT outcome is
  reported as unknown when the error happened during COMMIT;
- 2: invalid command line arguments (argparse);
- 130: interrupted by the user (KeyboardInterrupt).

Only the database name (`current_database()`) is printed; the connection
URL, SQL, parameters and exception texts of database errors never are.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.models_registry  # noqa: F401 - register every model before use
from app.core.config import get_settings
from app.seeds.base import seed_base
from app.seeds.common import SeedError, SeedReport
from app.seeds.demo import seed_demo

MODES: dict[str, Callable[[AsyncConnection], Awaitable[SeedReport]]] = {
    "base": seed_base,
    "demo": seed_demo,
}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


@dataclass
class _State:
    """Progress of the run, used to report the outcome truthfully."""

    phase: str = "start"  # start -> connect -> seed -> commit -> committed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.seeds",
        description="Seed: base — системные данные; demo — демо-зона и каталог (нужен base).",
    )
    parser.add_argument("mode", choices=sorted(MODES), help="режим seed: base или demo")
    return parser


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _sqlstate(exc: DBAPIError) -> str:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return f" (SQLSTATE {sqlstate})" if sqlstate else ""


def _outcome(state: _State) -> str:
    if state.phase == "commit":
        return (
            "Результат фиксации неизвестен: ошибка произошла во время COMMIT. "
            "Повторный запуск безопасен (seed идемпотентен)."
        )
    return "Изменения не сохранены (rollback)."


async def _execute(engine: AsyncEngine, mode: str, state: _State) -> SeedReport:
    # No try/except here: any exception leaves engine.begin() -> ROLLBACK.
    state.phase = "connect"
    async with engine.begin() as conn:
        db_name = await conn.scalar(text("SELECT current_database()"))
        print(f"База данных: {db_name}", flush=True)
        print(f"Режим: {mode}", flush=True)
        state.phase = "seed"
        report = await MODES[mode](conn)
        state.phase = "commit"  # leaving the block executes COMMIT
    state.phase = "committed"  # reached only after a successful COMMIT
    return report


async def _dispose(engine: AsyncEngine, state: _State) -> None:
    try:
        await engine.dispose()
    except Exception as exc:
        saved = "Изменения зафиксированы. " if state.phase == "committed" else ""
        _err(
            f"Предупреждение: {saved}Закрытие соединений завершилось ошибкой {type(exc).__name__}."
        )


async def run(mode: str, state: _State) -> int:
    try:
        database_url = get_settings().database_url  # ValidationError if not set
        engine = create_async_engine(database_url, poolclass=NullPool)
    except Exception as exc:
        _err(
            f"Seed не запущен: {type(exc).__name__}. Проверьте DATABASE_URL. "
            "Изменения не вносились."
        )
        return EXIT_ERROR

    try:
        report = await _execute(engine, mode, state)
    except SeedError as exc:
        _err(f"Ошибка seed: {exc}")
        _err(_outcome(state))
        return EXIT_ERROR
    except DBAPIError as exc:
        _err(f"Seed прерван: ошибка БД {type(exc).__name__}{_sqlstate(exc)}.")
        _err(_outcome(state))
        return EXIT_ERROR
    except Exception as exc:
        _err(f"Seed прерван: {type(exc).__name__}.")
        _err(_outcome(state))
        return EXIT_ERROR
    else:
        for line in report.lines():
            print(line, flush=True)
        print("Готово. Изменения зафиксированы.", flush=True)
        return EXIT_OK
    finally:
        await _dispose(engine, state)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)  # invalid arguments: SystemExit(2), no DB access
    state = _State()
    try:
        return asyncio.run(run(args.mode, state))
    except KeyboardInterrupt:
        if state.phase == "committed":
            _err("Seed прерван пользователем после фиксации: изменения сохранены.")
        elif state.phase == "commit":
            _err(
                "Seed прерван пользователем во время COMMIT: результат неизвестен. "
                "Повторный запуск безопасен."
            )
        else:
            _err("Seed прерван пользователем. Изменения не сохранены (rollback).")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
