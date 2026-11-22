"""Shared column types, value sets and CHECK helpers."""

from collections.abc import Iterable
from enum import StrEnum

from sqlalchemy import Numeric

# Money is always NUMERIC(12,2), never float (DATABASE_SCHEMA.md §2.3).
Money = Numeric(12, 2)
# Coordinates: NUMERIC(10,7) (DATABASE_SCHEMA.md §3.5, §7.2).
Coordinate = Numeric(10, 7)

# Phone format of Kyrgyzstan, stored normalized (DEC-89).
PHONE_PATTERN = r"^\+996[0-9]{9}$"


class Language(StrEnum):
    RU = "ru"
    KY = "ky"
    UZ = "uz"


def sql_in(column: str, values: Iterable[str]) -> str:
    """Render a CHECK expression `column IN ('a', 'b')` from fixed literals.

    Only used with values from StrEnum classes defined in code (never with
    user input), so quoting simple identifiers is safe.
    """
    items = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({items})"
