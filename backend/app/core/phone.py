"""Kyrgyz phone number normalization (DEC-89, API_SPECIFICATION.md §1.5).

Accepted input (spaces anywhere are ignored):
`+996 700 12 34 56`, `996700123456`, `0700123456`, `700123456`.
Stored form: `+996` followed by 9 digits (`app.db.types.PHONE_PATTERN`).
Anything else is rejected; the API maps the error to 422 VALIDATION_ERROR.
"""

import re

from app.db.types import PHONE_PATTERN

_INPUT = re.compile(r"(?:\+996|996|0)?([0-9]{9})")
_STORED = re.compile(PHONE_PATTERN)


class PhoneFormatError(ValueError):
    """The value is not a Kyrgyz phone number in an accepted form."""

    def __init__(self) -> None:
        super().__init__("phone must be +996 followed by 9 digits")


def normalize_phone(value: str) -> str:
    compact = re.sub(r" +", "", value.strip())
    match = _INPUT.fullmatch(compact)
    if match is None:
        raise PhoneFormatError
    normalized = f"+996{match.group(1)}"
    # Same rule as the database CHECK constraint.
    if not _STORED.fullmatch(normalized):  # pragma: no cover - guaranteed by _INPUT
        raise PhoneFormatError
    return normalized
