"""Phone normalization (DEC-89, API_SPECIFICATION.md §1.5)."""

import re

import pytest

from app.core.phone import PhoneFormatError, normalize_phone
from app.db.types import PHONE_PATTERN


@pytest.mark.parametrize(
    "raw",
    [
        "+996 700 12 34 56",
        "+996700123456",
        "996700123456",
        "0700123456",
        "700123456",
        "  +996 700 123 456  ",
        "0 700 12 34 56",
    ],
)
def test_accepted_forms_are_normalized(raw: str) -> None:
    normalized = normalize_phone(raw)
    assert normalized == "+996700123456"
    assert re.fullmatch(PHONE_PATTERN, normalized)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "70012345",  # 8 digits
        "7001234567",  # 10 digits without a prefix
        "+99670012345",  # +996 and 8 digits
        "+9967001234567",  # +996 and 10 digits
        "+7 700 123 45 67",  # other country
        "+0700123456",
        "00996700123456",
        "996-700-123-456",
        "(0700) 123456",
        "+996 70O 12 34 56",  # letter O
        "+996\t700123456",
        "+996 ７００ 12 34 56",  # full-width digits
        "٧٠٠١٢٣٤٥٦",  # Arabic-Indic digits
    ],
)
def test_other_values_are_rejected(raw: str) -> None:
    with pytest.raises(PhoneFormatError):
        normalize_phone(raw)


def test_error_is_a_value_error_without_the_input() -> None:
    with pytest.raises(ValueError, match=r"\+996") as info:
        normalize_phone("123")
    assert "123" not in str(info.value)
