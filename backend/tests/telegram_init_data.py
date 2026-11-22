"""Test helper: builds signed Telegram `initData` (API §2.3, DEC-154 п. 2).

Deliberately independent of `app.modules.telegram_auth`: it does not import
the application code, so a bug in the verifier cannot be mirrored here. The
helper itself is pinned by a known-answer vector computed with `openssl`
(see test_telegram_init_data.py), so both sides are checked against a third
implementation.
"""

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote

# Throw-away tokens for tests only; never a real bot token.
TEST_BOT_TOKEN = "123456789:TEST-unit-token-not-a-real-bot"  # noqa: S105 - test data
OTHER_BOT_TOKEN = "987654321:OTHER-unit-token-not-a-real-bot"  # noqa: S105 - test data


def sign(fields: dict[str, str], bot_token: str = TEST_BOT_TOKEN) -> str:
    """hex(HMAC_SHA256(key=HMAC_SHA256(key="WebAppData", msg=token), msg=dcs))."""
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k != "hash")
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()


def encode(fields: dict[str, str] | list[tuple[str, str]]) -> str:
    """URL-encode like Telegram clients: every value percent-encoded."""
    pairs = fields.items() if isinstance(fields, dict) else fields
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs)


def user_json(telegram_id: int = 279058397, **extra: Any) -> str:
    user: dict[str, Any] = {"id": telegram_id, "first_name": "Test", **extra}
    return json.dumps(user, ensure_ascii=False, separators=(",", ":"))


def make_fields(
    *,
    telegram_id: int = 279058397,
    auth_date: int | None = None,
    user: str | None = None,
    extra: dict[str, str] | None = None,
    **user_fields: Any,
) -> dict[str, str]:
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": user if user is not None else user_json(telegram_id, **user_fields),
    }
    fields.update(extra or {})
    return fields


def init_data(
    *,
    bot_token: str = TEST_BOT_TOKEN,
    telegram_id: int = 279058397,
    auth_date: int | None = None,
    user: str | None = None,
    extra: dict[str, str] | None = None,
    **user_fields: Any,
) -> str:
    """A correctly signed `initData` string (fresh auth_date by default)."""
    fields = make_fields(
        telegram_id=telegram_id, auth_date=auth_date, user=user, extra=extra, **user_fields
    )
    fields["hash"] = sign(fields, bot_token)
    return encode(fields)
