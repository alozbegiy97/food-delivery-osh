"""Unit tests of the `initData` verifier and lock-key fold (no database).

DEC-142 K1-B, DEC-154 пп. 1-3, 7, U2, D5. The current time is passed in,
so every boundary is exact. Signed data comes from tests/telegram_init_data.py,
which does not import the application; both are pinned by a known-answer
vector computed with `openssl dgst -mac HMAC` (a third implementation).
"""

import hashlib
import hmac
import json
from typing import Any

import pytest

from app.modules.telegram_auth.init_data import (
    InvalidInitData,
    data_check_string,
    expected_hash,
    verify_init_data,
)
from app.modules.telegram_auth.locks import LOCK_NAMESPACE, fold_telegram_id
from tests.telegram_init_data import (
    OTHER_BOT_TOKEN,
    TEST_BOT_TOKEN,
    encode,
    init_data,
    make_fields,
    sign,
    user_json,
)

NOW = 1_700_000_000
MAX_AGE = 3600
SKEW = 60
MAX_LENGTH = 4096


def verify(raw: str, *, now: int = NOW, token: str = TEST_BOT_TOKEN, max_length: int = MAX_LENGTH):  # noqa: ANN201
    return verify_init_data(
        raw,
        bot_token=token,
        now=now,
        max_age_seconds=MAX_AGE,
        clock_skew_seconds=SKEW,
        max_length=max_length,
    )


def rejected(raw: str, **kwargs: Any) -> None:
    with pytest.raises(InvalidInitData) as caught:
        verify(raw, **kwargs)
    # No detail, no chained cause: nothing of the input can leak.
    assert str(caught.value) == "invalid init data"
    assert caught.value.__cause__ is None


def signed(fields: dict[str, str], token: str = TEST_BOT_TOKEN) -> str:
    return encode({**fields, "hash": sign(fields, token)})


# --------------------------------------------------------------------------
# Known-answer vector (openssl, independent of Python and of the app)
# --------------------------------------------------------------------------
#
# TOKEN="123456789:TEST-unit-token-not-a-real-bot"
# SK=$(printf %s "$TOKEN" | openssl dgst -sha256 -mac HMAC -macopt key:WebAppData -r)
# printf %s "$DCS" | openssl dgst -sha256 -mac HMAC -macopt hexkey:$SK -r
KAT_SECRET_KEY_HEX = "28b220c91da93c8237311e54deaee13f8e211914ae1d1bd3c3b7a70bb5acb670"  # noqa: S105 - test vector
KAT_HASH = "a9ad52733e9825e8a276ca1603309aedb417feb8322642e911e4c6c8b4321c5a"
# Same data with key and message swapped (key=token, msg="WebAppData").
KAT_SWAPPED_HASH = "23161e0e9e78a59fe50015f2b0b06205ccb2fbd3e91439903d73e7a7b54f2455"
KAT_USER = (
    '{"id":279058397,"first_name":"Vladislav","last_name":"Kibenko",'
    '"username":"vdkfrost","language_code":"ru","allows_write_to_pm":true}'
)
KAT_FIELDS = {
    "auth_date": "1700000000",
    "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
    "signature": "test-signature-value",
    "user": KAT_USER,
}


def test_known_answer_vector_matches_openssl() -> None:
    secret = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).hexdigest()
    assert secret == KAT_SECRET_KEY_HEX
    assert expected_hash(TEST_BOT_TOKEN, data_check_string(KAT_FIELDS)) == KAT_HASH
    assert sign(KAT_FIELDS) == KAT_HASH  # the test helper agrees as well

    result = verify(encode({**KAT_FIELDS, "hash": KAT_HASH}))
    assert result.telegram_id == 279058397
    assert (result.first_name, result.last_name, result.username) == (
        "Vladislav",
        "Kibenko",
        "vdkfrost",
    )
    assert result.language_code == "ru"
    assert result.allows_write_to_pm is True
    assert result.auth_date == NOW


def test_swapped_hmac_arguments_are_rejected() -> None:
    """Proves the argument order: key="WebAppData", message=bot token."""
    rejected(encode({**KAT_FIELDS, "hash": KAT_SWAPPED_HASH}))


def test_data_check_string_excludes_only_hash_and_sorts_keys() -> None:
    fields = {"user": "u", "hash": "h", "auth_date": "1", "signature": "s", "a": ""}
    assert data_check_string(fields) == "a=\nauth_date=1\nsignature=s\nuser=u"


# --------------------------------------------------------------------------
# Signature
# --------------------------------------------------------------------------


def test_valid_data_with_fresh_signature() -> None:
    result = verify(init_data(auth_date=NOW, allows_write_to_pm=False))
    assert result.telegram_id == 279058397
    assert result.allows_write_to_pm is False


@pytest.mark.parametrize("field", ["auth_date", "query_id", "user", "signature"])
def test_any_changed_field_breaks_the_signature(field: str) -> None:
    fields = make_fields(auth_date=NOW, extra={"signature": "sig"})
    good = sign(fields)
    tampered = dict(fields)
    tampered[field] = {
        "auth_date": str(NOW - 1),
        "query_id": "other",
        "user": user_json(1),
        "signature": "sig2",
    }[field]
    rejected(encode({**tampered, "hash": good}))


def test_signature_field_is_part_of_the_check_string() -> None:
    fields = make_fields(auth_date=NOW, extra={"signature": "abc"})
    without_signature = {k: v for k, v in fields.items() if k != "signature"}
    # Hash computed as if `signature` were excluded must not verify.
    rejected(encode({**fields, "hash": sign(without_signature)}))
    assert verify(signed(fields)).telegram_id == 279058397


def test_added_or_removed_field_breaks_the_signature() -> None:
    fields = make_fields(auth_date=NOW)
    good = sign(fields)
    rejected(encode({**fields, "start_param": "x", "hash": good}))
    rejected(encode({k: v for k, v in {**fields, "hash": good}.items() if k != "query_id"}))


def test_other_bot_token_is_rejected() -> None:
    rejected(init_data(auth_date=NOW, bot_token=OTHER_BOT_TOKEN))
    rejected(init_data(auth_date=NOW), token=OTHER_BOT_TOKEN)


@pytest.mark.parametrize(
    "bad_hash",
    [
        "",
        "A" * 64,  # uppercase hex
        "0" * 63,
        "0" * 65,
        "g" * 64,
        " " + "0" * 63,
    ],
)
def test_malformed_hash_is_rejected(bad_hash: str) -> None:
    fields = make_fields(auth_date=NOW)
    rejected(encode({**fields, "hash": bad_hash}))


def test_uppercase_version_of_the_right_hash_is_rejected() -> None:
    fields = make_fields(auth_date=NOW)
    rejected(encode({**fields, "hash": sign(fields).upper()}))


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["hash", "auth_date", "user"])
def test_required_fields(missing: str) -> None:
    fields = make_fields(auth_date=NOW)
    fields["hash"] = sign(fields)
    del fields[missing]
    if missing != "hash":  # re-sign so only the missing field is the reason
        fields["hash"] = sign({k: v for k, v in fields.items() if k != "hash"})
    rejected(encode(fields))


@pytest.mark.parametrize("duplicate", ["hash", "auth_date", "user", "query_id"])
def test_duplicate_keys_are_rejected(duplicate: str) -> None:
    fields = make_fields(auth_date=NOW)
    fields["hash"] = sign(fields)
    pairs = [*fields.items(), (duplicate, fields[duplicate])]
    rejected(encode(pairs))


@pytest.mark.parametrize(
    "raw",
    ["", "hash", "=x", "a=1&&b=2", "a=1&=2", "%ZZ=1", "user=%C3%28"],
)
def test_malformed_query_strings_are_rejected(raw: str) -> None:
    rejected(raw)


def test_percent_encoding_and_plus_are_decoded_before_signing() -> None:
    fields = make_fields(auth_date=NOW, first_name="Анна Мария", last_name="O'Neil & Co")
    result = verify(signed(fields))
    assert (result.first_name, result.last_name) == ("Анна Мария", "O'Neil & Co")
    # `+` in the query string means a space, as in URLSearchParams.
    raw = signed(fields).replace("%20", "+")
    assert verify(raw).first_name == "Анна Мария"


# --------------------------------------------------------------------------
# Length (DEC-154 п. 1, D5)
# --------------------------------------------------------------------------


def _padded(length: int) -> str:
    fields = make_fields(auth_date=NOW, extra={"pad": ""})
    base = len(signed(fields))
    fields["pad"] = "x" * (length - base)
    raw = signed(fields)
    assert len(raw) == length
    return raw


def test_length_4096_is_accepted_and_4097_rejected() -> None:
    assert verify(_padded(4096)).telegram_id == 279058397
    rejected(_padded(4097))


def test_length_counts_characters_not_bytes() -> None:
    fields = make_fields(auth_date=NOW, first_name="Ө")
    raw = signed(fields)
    assert verify(raw, max_length=len(raw)).first_name == "Ө"
    rejected(raw, max_length=len(raw) - 1)


# --------------------------------------------------------------------------
# Time (after the signature)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth_date", "ok"),
    [
        (NOW - MAX_AGE, True),
        (NOW - MAX_AGE - 1, False),
        (NOW, True),
        (NOW + SKEW, True),
        (NOW + SKEW + 1, False),
    ],
)
def test_auth_date_boundaries(auth_date: int, ok: bool) -> None:
    raw = init_data(auth_date=auth_date)
    if ok:
        assert verify(raw).auth_date == auth_date
    else:
        rejected(raw)


@pytest.mark.parametrize("auth_date", ["", "-1", "1.5", "1e9", " 1700000000", "0x10", "١٧٠٠"])
def test_auth_date_must_be_plain_digits(auth_date: str) -> None:
    rejected(signed({**make_fields(), "auth_date": auth_date}))


# --------------------------------------------------------------------------
# user JSON
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user",
    [
        "not json",
        "[]",
        '"text"',
        "null",
        "{}",
        '{"id":true,"first_name":"T"}',
        '{"id":"279058397","first_name":"T"}',
        '{"id":0,"first_name":"T"}',
        '{"id":-5,"first_name":"T"}',
        '{"id":1.0,"first_name":"T"}',
        '{"id":9223372036854775808,"first_name":"T"}',
        '{"id":1,"id":2,"first_name":"T"}',
        '{"id":1,"first_name":5}',
        '{"id":1,"first_name":"T","last_name":null}',
        '{"id":1,"first_name":"T","username":["a"]}',
        '{"id":1,"first_name":"T","language_code":1}',
        '{"id":1,"first_name":"T","is_bot":true}',
        '{"id":1,"first_name":"T","is_bot":"false"}',
        '{"id":1,"first_name":"T","allows_write_to_pm":"true"}',
        '{"id":1,"first_name":"T","allows_write_to_pm":1}',
        "[" * 3000 + "]" * 3000,
    ],
)
def test_invalid_user_objects_are_rejected(user: str) -> None:
    rejected(signed(make_fields(auth_date=NOW, user=user)), max_length=20_000)


def test_user_defaults_and_limits() -> None:
    result = verify(signed(make_fields(auth_date=NOW, user='{"id":9223372036854775807}')))
    assert result.telegram_id == 2**63 - 1
    assert (result.first_name, result.last_name, result.username) == ("", None, None)
    assert result.language_code is None
    assert result.allows_write_to_pm is False  # missing -> false (DEC-154 п. 3)


def test_is_bot_false_is_accepted() -> None:
    assert verify(init_data(auth_date=NOW, is_bot=False)).telegram_id == 279058397


@pytest.mark.parametrize(
    ("username", "stored"),
    [("a" * 100, "a" * 100), ("a" * 101, None), ("", None), ("vdkfrost", "vdkfrost")],
)
def test_username_longer_than_100_becomes_none(username: str, stored: str | None) -> None:
    assert verify(init_data(auth_date=NOW, username=username)).username == stored


def test_unknown_user_fields_are_ignored() -> None:
    raw = init_data(auth_date=NOW, photo_url="https://t.me/x.jpg", is_premium=True)
    assert verify(raw).telegram_id == 279058397


def test_result_is_immutable() -> None:
    result = verify(init_data(auth_date=NOW))
    with pytest.raises(AttributeError):
        result.telegram_id = 1  # type: ignore[misc]


# --------------------------------------------------------------------------
# Advisory lock key
# --------------------------------------------------------------------------


@pytest.mark.parametrize("telegram_id", [1, 2**31 - 1, 2**31, 2**32, 2**52, 2**63 - 1])
def test_fold_fits_int4_and_is_deterministic(telegram_id: int) -> None:
    key = fold_telegram_id(telegram_id)
    assert -(2**31) <= key < 2**31
    assert key == fold_telegram_id(telegram_id)
    assert -(2**31) <= LOCK_NAMESPACE < 2**31


def test_fold_collision_pair_exists() -> None:
    first = 279058397
    second = first ^ (1 << 32) ^ 1  # high word 1, low word adjusted
    assert first != second
    assert fold_telegram_id(first) == fold_telegram_id(second)


def test_user_json_helper_is_valid_json() -> None:
    assert json.loads(user_json(5, username="u"))["id"] == 5


# --------------------------------------------------------------------------
# U1: only lock_timeout becomes TELEGRAM_BUSY
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sqlstate", "busy"),
    [("55P03", True), ("40P01", False), ("40001", False), ("23505", False), (None, False)],
    ids=["lock_timeout", "deadlock", "serialization", "unique", "no-sqlstate"],
)
def test_only_lock_not_available_is_busy(sqlstate: str | None, busy: bool) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.modules.telegram_auth.locks import is_lock_timeout

    class FakeDriverError(Exception):
        pass

    orig = FakeDriverError()
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    assert is_lock_timeout(DBAPIError("SELECT 1", None, orig)) is busy
