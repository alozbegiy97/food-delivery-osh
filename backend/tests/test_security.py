"""Security primitives and auth settings (DEC-96, DEC-140; package S3-A).

No database is used. Tests run with the per-run JWT secret and light Argon2
parameters set in `conftest.py`; the real secret from `.env` is never used.
"""

import logging
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings, get_settings
from app.core.security import (
    AccessToken,
    InvalidAccessTokenError,
    PasswordPolicyError,
    check_password_policy,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)

SECRET = os.environ["JWT_SECRET_KEY"]


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": "postgresql+psycopg://u@127.0.0.1:1/x"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY")
    with pytest.raises(ValidationError) as info:
        _settings()
    assert "jwt_secret_key" in str(info.value)


def test_app_does_not_start_without_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.delenv("JWT_SECRET_KEY")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        create_app()


@pytest.mark.parametrize("secret", ["", "Zq9", "Zq9#Wk7!" * 3 + "Xy3$Vb8"])  # 0, 3, 31
def test_short_jwt_secret_is_rejected_without_echoing_it(secret: str) -> None:
    assert len(secret) < 32
    with pytest.raises(ValidationError) as info:
        _settings(jwt_secret_key=secret)
    message = str(info.value)
    assert "jwt_secret_key" in message
    if secret:
        assert secret not in message


def test_jwt_secret_of_32_chars_is_accepted_and_hidden() -> None:
    secret = "k" * 32
    settings = _settings(jwt_secret_key=secret)
    assert settings.jwt_secret_key.get_secret_value() == secret
    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in settings.model_dump_json()


def test_csrf_origins_are_split() -> None:
    settings = _settings(csrf_trusted_origins=" http://localhost:5173 ,https://shop.example ")
    assert settings.csrf_trusted_origins == ["http://localhost:5173", "https://shop.example"]
    assert _settings(csrf_trusted_origins="").csrf_trusted_origins == []


@pytest.mark.parametrize(
    "origin",
    ["*", "null", "localhost:5173", "http://localhost:5173/", "http://a/b", "ftp://a"],
)
def test_invalid_csrf_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValidationError, match="CSRF trusted origin"):
        _settings(csrf_trusted_origins=origin)


def test_argon2_defaults_are_rfc_9106(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ARGON2_TIME_COST", "ARGON2_MEMORY_COST_KIB", "ARGON2_PARALLELISM"):
        monkeypatch.delenv(name)
    settings = _settings()
    assert (
        settings.argon2_time_cost,
        settings.argon2_memory_cost_kib,
        settings.argon2_parallelism,
    ) == (3, 65536, 4)


def test_argon2_memory_must_cover_parallelism() -> None:
    with pytest.raises(ValidationError, match="ARGON2_MEMORY_COST_KIB"):
        _settings(argon2_memory_cost_kib=16, argon2_parallelism=4)


def test_tests_use_light_argon2_and_own_secret() -> None:
    settings = get_settings()
    assert settings.argon2_time_cost == 1
    assert settings.argon2_memory_cost_kib == 1024
    assert settings.jwt_secret_key.get_secret_value() == SECRET


# --------------------------------------------------------------------------
# Password policy (DEC-96)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["abcdef12", "a" * 127 + "1", "пароль12", "Сыр5сыр5", "Oʻzbek99", "  a1    "],
)
def test_valid_passwords(password: str) -> None:
    check_password_policy(password)


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("", "too_short"),
        ("abcde12", "too_short"),  # 7
        ("a" * 128 + "1", "too_long"),  # 129
        ("12345678", "no_letter"),
        ("!!!!1234", "no_letter"),
        ("abcdefgh", "no_digit"),
        ("пароль!!", "no_digit"),
    ],
)
def test_invalid_passwords(password: str, reason: str) -> None:
    with pytest.raises(PasswordPolicyError) as info:
        check_password_policy(password)
    assert info.value.reason == reason
    assert password not in str(info.value) or password == ""


def test_password_length_boundaries() -> None:
    check_password_policy("a" * 7 + "1")  # 8
    check_password_policy("a" * 127 + "1")  # 128


def test_length_counts_characters_not_bytes() -> None:
    check_password_policy("ж" * 127 + "1")  # 128 characters, 255 bytes


# --------------------------------------------------------------------------
# Argon2id
# --------------------------------------------------------------------------


def test_hash_and_verify() -> None:
    password_hash = hash_password("correct1horse")
    assert password_hash.startswith("$argon2id$")
    assert "correct1horse" not in password_hash
    assert verify_password(password_hash, "correct1horse")
    assert not verify_password(password_hash, "wrong1horse")
    assert hash_password("correct1horse") != password_hash  # random salt


@pytest.mark.parametrize("broken", ["", "not-a-hash", "$argon2id$v=19$m=1,t=1,p=1$xx$yy"])
def test_malformed_hash_is_a_mismatch(broken: str) -> None:
    assert verify_password(broken, "whatever1") is False


def test_rehash_needed_after_parameter_change(monkeypatch: pytest.MonkeyPatch) -> None:
    old_hash = hash_password("correct1horse")
    assert not password_needs_rehash(old_hash)
    monkeypatch.setenv("ARGON2_TIME_COST", "2")
    get_settings.cache_clear()
    assert password_needs_rehash(old_hash)
    assert verify_password(old_hash, "correct1horse")  # old hash still verifies
    assert password_needs_rehash("not-a-hash")


def test_hash_uses_configured_parameters() -> None:
    assert "$m=1024,t=1,p=1$" in hash_password("correct1horse")


def test_dummy_verification_runs_without_error() -> None:
    verify_dummy_password("anything1")
    verify_dummy_password("")


# --------------------------------------------------------------------------
# Access JWT
# --------------------------------------------------------------------------


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    access = create_access_token(user_id)
    assert isinstance(access, AccessToken)
    assert access.expires_in == 15 * 60
    assert decode_access_token(access.token) == user_id
    assert access.token not in repr(access)


def test_access_token_claims() -> None:
    user_id = uuid.uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    access = create_access_token(user_id, now=now)
    header = jwt.get_unverified_header(access.token)
    claims = jwt.decode(access.token, SECRET, algorithms=["HS256"])
    assert header["alg"] == "HS256"
    assert claims == {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }


def test_expired_token_is_rejected() -> None:
    access = create_access_token(uuid.uuid4(), now=datetime.now(UTC) - timedelta(minutes=16))
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(access.token)


def _forge(claims: dict[str, object], key: str = SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm)


def _claims(**overrides: object) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


@pytest.mark.parametrize(
    "token_factory",
    [
        pytest.param(lambda: _forge(_claims(), key="x" * 32), id="other-secret"),
        pytest.param(lambda: _forge(_claims(), algorithm="HS512"), id="hs512"),
        pytest.param(lambda: jwt.encode(_claims(), None, algorithm="none"), id="alg-none"),
        pytest.param(lambda: _forge(_claims(type="refresh")), id="type-refresh"),
        pytest.param(lambda: _forge(_claims(type=None)), id="no-type"),
        pytest.param(lambda: _forge(_claims(sub=None)), id="no-sub"),
        pytest.param(lambda: _forge(_claims(exp=None)), id="no-exp"),
        pytest.param(lambda: _forge(_claims(iat=None)), id="no-iat"),
        pytest.param(lambda: _forge(_claims(sub="not-a-uuid")), id="bad-sub"),
        pytest.param(lambda: "not.a.jwt", id="garbage"),
        pytest.param(lambda: "", id="empty"),
    ],
)
def test_invalid_tokens_are_rejected(token_factory) -> None:  # noqa: ANN001
    with pytest.raises(InvalidAccessTokenError) as info:
        decode_access_token(token_factory())
    assert str(info.value) == "invalid access token"


def test_tampered_payload_is_rejected() -> None:
    header, _, signature = create_access_token(uuid.uuid4()).token.split(".")
    other_payload = _forge(_claims()).split(".")[1]
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(f"{header}.{other_payload}.{signature}")


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        create_access_token(uuid.uuid4(), now=datetime(2026, 1, 1))  # noqa: DTZ001


def test_secrets_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    password_hash = hash_password("correct1horse")
    verify_password(password_hash, "correct1horse")
    access = create_access_token(uuid.uuid4())
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(access.token + "x")
    text = caplog.text
    for value in (SECRET, "correct1horse", password_hash, access.token):
        assert value not in text


def test_module_has_no_logger() -> None:
    assert not hasattr(security, "logger")


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("User@Example.COM", "user@example.com"),
        ("  a.b@example.test ", "a.b@example.test"),
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected
