"""Verification of Telegram Mini App `initData` (DEC-142, DEC-154 пп. 1-2).

Pure function: no database, no I/O, no logging; the current time is passed
in, so tests are deterministic. Steps, in this order:

1. length 1..max_length characters (DEC-154 п. 1; longer -> refused);
2. strict query-string parsing: every pair must be `key=value`, values are
   percent-decoded as UTF-8 (invalid UTF-8 is refused), a key may appear
   only once (two `hash` fields included);
3. required fields `hash`, `auth_date`, `user`; `hash` is exactly 64
   lowercase hex characters;
4. signature, the official Telegram WebApp HMAC scheme (DEC-154 п. 2):
   data_check_string = all received fields except `hash` (so `signature`,
   if present, stays in it), as `key=value`, sorted by key, joined by "\\n";
   secret_key = HMAC-SHA256(key=b"WebAppData", msg=bot_token);
   expected = hex(HMAC-SHA256(key=secret_key, msg=data_check_string));
   compared with `hmac.compare_digest`. The separate Ed25519 check for third
   parties is not used;
5. only then the data is interpreted: `auth_date` (digits only) not older
   than max_age and not later than now + clock_skew; `user` is a JSON
   object without duplicate keys; `id` is an int (not bool) in
   1..2^63-1; `is_bot` must not be true; optional fields must have their
   exact types (nothing is coerced); a missing `allows_write_to_pm` is
   false; a `username` longer than 100 characters becomes None (U2).

Any failure raises `InvalidInitData` without a message or a chained
exception, so neither the input nor the reason can leak into logs or
responses (the API answers `401 INVALID_TELEGRAM_AUTH`).
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

WEBAPP_DATA_KEY = b"WebAppData"
TELEGRAM_ID_MAX = 2**63 - 1  # telegram_links.telegram_chat_id is BIGINT
USERNAME_MAX_LENGTH = 100  # telegram_links.telegram_username VARCHAR(100)

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_AUTH_DATE_PATTERN = re.compile(r"[0-9]{1,12}")
_OPTIONAL_STRINGS = ("first_name", "last_name", "username", "language_code")
_OPTIONAL_BOOLS = ("is_bot", "allows_write_to_pm")


class InvalidInitData(Exception):  # noqa: N818 - domain name, mapped to 401
    """`initData` failed verification; deliberately carries no details."""

    def __init__(self) -> None:
        super().__init__("invalid init data")


@dataclass(frozen=True, slots=True)
class VerifiedTelegramUser:
    """Data taken from a verified `initData` only (DEC-142 K1-B п. 3)."""

    telegram_id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    allows_write_to_pm: bool
    auth_date: int


def _parse_pairs(raw: str) -> dict[str, str]:
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, errors="strict")
    except ValueError:  # malformed pair or invalid UTF-8 (UnicodeDecodeError)
        raise InvalidInitData from None
    fields: dict[str, str] = {}
    for key, value in pairs:
        if not key or key in fields:
            raise InvalidInitData
        fields[key] = value
    return fields


def data_check_string(fields: dict[str, str]) -> str:
    """Every field except `hash`, `key=value`, sorted by key, joined by "\\n"."""
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")


def expected_hash(bot_token: str, check_string: str) -> str:
    secret_key = hmac.new(WEBAPP_DATA_KEY, bot_token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInitData
        result[key] = value
    return result


def _parse_user(raw_user: str) -> dict[str, Any]:
    try:
        user = json.loads(raw_user, object_pairs_hook=_no_duplicate_keys)
    except ValueError, RecursionError:  # invalid JSON; absurdly deep nesting
        raise InvalidInitData from None
    if not isinstance(user, dict):
        raise InvalidInitData
    telegram_id = user.get("id")
    # bool is a subclass of int: excluded explicitly.
    if type(telegram_id) is not int or not 1 <= telegram_id <= TELEGRAM_ID_MAX:
        raise InvalidInitData
    for name in _OPTIONAL_STRINGS:
        if name in user and type(user[name]) is not str:
            raise InvalidInitData
    for name in _OPTIONAL_BOOLS:
        if name in user and type(user[name]) is not bool:
            raise InvalidInitData
    if user.get("is_bot") is True:
        raise InvalidInitData
    return user


def verify_init_data(
    raw: str,
    *,
    bot_token: str,
    now: int,
    max_age_seconds: int,
    clock_skew_seconds: int,
    max_length: int,
) -> VerifiedTelegramUser:
    """Verify `raw` (`Telegram.WebApp.initData`); `now` is a Unix time in seconds."""
    if not isinstance(raw, str) or not 1 <= len(raw) <= max_length:
        raise InvalidInitData
    fields = _parse_pairs(raw)
    received_hash = fields.get("hash")
    if received_hash is None or "auth_date" not in fields or "user" not in fields:
        raise InvalidInitData
    if not _HASH_PATTERN.fullmatch(received_hash):
        raise InvalidInitData
    expected = expected_hash(bot_token, data_check_string(fields))
    if not hmac.compare_digest(expected, received_hash):
        raise InvalidInitData

    # Signed by Telegram from here on; still validated before use.
    raw_auth_date = fields["auth_date"]
    if not _AUTH_DATE_PATTERN.fullmatch(raw_auth_date):
        raise InvalidInitData
    auth_date = int(raw_auth_date)
    if now - auth_date > max_age_seconds or auth_date - now > clock_skew_seconds:
        raise InvalidInitData

    user = _parse_user(fields["user"])
    username = user.get("username")
    if username is not None and not 1 <= len(username) <= USERNAME_MAX_LENGTH:
        username = None  # U2: never a database error because of a username
    return VerifiedTelegramUser(
        telegram_id=user["id"],
        first_name=user.get("first_name", ""),
        last_name=user.get("last_name"),
        username=username,
        language_code=user.get("language_code"),
        allows_write_to_pm=user.get("allows_write_to_pm", False),
        auth_date=auth_date,
    )
