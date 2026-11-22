"""CLI: `python -m app.cli create-admin` (DEC-88).

Asks for the name and e-mail, then the password twice without echo. One
transaction: COMMIT only after the admin row is written.

Exit codes: 0 created; 1 refused or failed (nothing saved); 2 invalid
arguments; 130 interrupted. The password, the database URL and SQL are
never printed.
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

import app.db.models_registry  # noqa: F401 - register every model before use
from app.cli.create_admin import CreateAdminError, create_first_admin
from app.core.config import get_settings
from app.db.session import create_db_engine

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _validation_messages(exc: ValidationError) -> str:
    # Field names and rule messages only; the input values are never echoed.
    return "; ".join(
        f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()
    )


async def _create(email: str, full_name: str, password: str) -> None:
    engine = create_db_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await create_first_admin(conn, email=email, full_name=full_name, password=password)
    finally:
        await engine.dispose()


def create_admin_command() -> int:
    try:
        full_name = input("Имя администратора: ")
        email = input("Email (логин): ")
        password = getpass.getpass("Пароль: ")
        if getpass.getpass("Повторите пароль: ") != password:
            _err("Пароли не совпадают. Администратор не создан.")
            return EXIT_ERROR
        asyncio.run(_create(email, full_name, password))
    except KeyboardInterrupt:
        _err("Прервано. Администратор не создан.")
        return EXIT_INTERRUPTED
    except ValidationError as exc:
        _err(f"Неверные данные: {_validation_messages(exc)}. Администратор не создан.")
        return EXIT_ERROR
    except CreateAdminError as exc:
        _err(f"{exc} Администратор не создан.")
        return EXIT_ERROR
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        _err(f"Ошибка базы данных (SQLSTATE {sqlstate}). Администратор не создан.")
        return EXIT_ERROR
    print(f"Администратор создан: {email.strip().lower()}", flush=True)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-admin", help="создать первого администратора (DEC-88)")
    parser.parse_args(argv)
    return create_admin_command()


if __name__ == "__main__":
    sys.exit(main())
