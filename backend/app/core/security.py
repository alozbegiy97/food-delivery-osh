"""Security primitives: password policy, Argon2id, access JWT (DEC-96, DEC-140).

- Password policy (DEC-96): 8-128 characters (Unicode code points), at
  least one letter (any Unicode letter) and one digit (Unicode decimal
  digit). The password is never stripped or otherwise changed.
- Argon2id parameters come from the settings (RFC 9106 by default; tests use
  lighter values). Hashing is CPU-bound: async code must call these
  functions in a thread pool.
- Access JWT: HS256 only, claims `sub`, `type=access`, `iat`, `exp`; roles
  and flags are never put into the token (DEC-66).

Nothing here logs or returns passwords, hashes or tokens in error messages.
"""

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a secret
_REQUIRED_CLAIMS = ["sub", "type", "iat", "exp"]


# --------------------------------------------------------------------------
# Password policy
# --------------------------------------------------------------------------


class PasswordPolicyError(ValueError):
    """Password does not satisfy DEC-96. `reason` is a stable code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "password must be 8-128 characters long and contain at least one letter and one digit"
        )


def check_password_policy(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError("too_short")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError("too_long")
    if not any(ch.isalpha() for ch in password):
        raise PasswordPolicyError("no_letter")
    if not any(ch.isdecimal() for ch in password):
        raise PasswordPolicyError("no_digit")


# --------------------------------------------------------------------------
# Argon2id
# --------------------------------------------------------------------------


@lru_cache
def _hasher(time_cost: int, memory_cost: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


def get_password_hasher() -> PasswordHasher:
    settings = get_settings()
    return _hasher(
        settings.argon2_time_cost, settings.argon2_memory_cost_kib, settings.argon2_parallelism
    )


def hash_password(password: str) -> str:
    return get_password_hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True only for a matching password; a malformed hash is a mismatch."""
    try:
        return get_password_hasher().verify(password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with other parameters (rehash on login)."""
    try:
        return get_password_hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache
def _dummy_hash(time_cost: int, memory_cost: int, parallelism: int) -> str:
    return _hasher(time_cost, memory_cost, parallelism).hash(secrets.token_urlsafe(32))


def verify_dummy_password(password: str) -> None:
    """Spend the same time as a real check when the email is unknown (DEC-140)."""
    settings = get_settings()
    dummy = _dummy_hash(
        settings.argon2_time_cost, settings.argon2_memory_cost_kib, settings.argon2_parallelism
    )
    verify_password(dummy, password)


# --------------------------------------------------------------------------
# Access JWT
# --------------------------------------------------------------------------


class InvalidAccessTokenError(Exception):
    """Token is malformed, expired, signed differently or not an access token."""

    def __init__(self) -> None:
        super().__init__("invalid access token")


@dataclass(frozen=True)
class AccessToken:
    token: str = field(repr=False)
    expires_in: int  # seconds


def _secret() -> str:
    return get_settings().jwt_secret_key.get_secret_value()


def create_access_token(user_id: uuid.UUID, *, now: datetime | None = None) -> AccessToken:
    issued = (now or datetime.now(UTC)).replace(microsecond=0)
    if issued.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    lifetime = timedelta(minutes=get_settings().access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(issued.timestamp()),
        "exp": int((issued + lifetime).timestamp()),
    }
    token = jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id from a valid access token or raise
    `InvalidAccessTokenError` (the API answers 401 UNAUTHORIZED)."""
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
        )
        if claims.get("type") != ACCESS_TOKEN_TYPE:
            raise InvalidAccessTokenError
        return uuid.UUID(str(claims["sub"]))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidAccessTokenError from exc


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    """Emails are stored and compared in lowercase (DATABASE_SCHEMA.md §3.1)."""
    return email.strip().lower()
