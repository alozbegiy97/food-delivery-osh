"""Request and response schemas of `/auth` (DEC-140, DEC-141).

Normalization happens here, so services receive clean values:

- email: surrounding whitespace removed, format checked by email-validator
  without DNS, stored and compared in lowercase, at most 255 characters;
- full_name: surrounding whitespace removed, 1-150 Unicode characters, no
  control characters;
- phone: DEC-89 normalization;
- password: DEC-96 policy, never stripped or changed.

Error messages never contain the submitted values.
"""

import unicodedata
import uuid
from typing import TYPE_CHECKING, Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.phone import normalize_phone
from app.core.security import check_password_policy, normalize_email

if TYPE_CHECKING:
    from app.modules.auth.dependencies import CurrentUser

EMAIL_MAX_LENGTH = 255
FULL_NAME_MAX_LENGTH = 150
# Login and current-password fields are not checked against the policy (that
# would reveal details); this cap only bounds the Argon2 input size.
_LOGIN_PASSWORD_MAX_LENGTH = 1024


def _email(value: str) -> str:
    normalized = normalize_email(value)
    if not normalized or len(normalized) > EMAIL_MAX_LENGTH:
        raise ValueError(f"email must be 1-{EMAIL_MAX_LENGTH} characters long")
    try:
        validate_email(normalized, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("invalid email address") from None
    return normalized


def _full_name(value: str) -> str:
    stripped = value.strip()
    if not 1 <= len(stripped) <= FULL_NAME_MAX_LENGTH:
        raise ValueError(f"full name must be 1-{FULL_NAME_MAX_LENGTH} characters long")
    if any(unicodedata.category(ch) == "Cc" for ch in stripped):
        raise ValueError("full name must not contain control characters")
    return stripped


def _new_password(value: str) -> str:
    check_password_policy(value)  # PasswordPolicyError is a ValueError
    return value


def _phone(value: str | None) -> str | None:
    return None if value is None else normalize_phone(value)


Email = Annotated[str, AfterValidator(_email)]
FullName = Annotated[str, AfterValidator(_full_name)]
NewPassword = Annotated[str, AfterValidator(_new_password)]
Phone = Annotated[str | None, AfterValidator(_phone)]
AnyPassword = Annotated[str, Field(min_length=1, max_length=_LOGIN_PASSWORD_MAX_LENGTH)]


class _Request(BaseModel):
    # Unknown fields (role, is_active, user_id, ...) are rejected (DEC-141).
    # hide_input_in_errors: error texts never contain submitted values (passwords).
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RegisterRequest(_Request):
    email: Email
    password: NewPassword
    full_name: FullName
    phone: Phone = None
    preferred_language: Literal["ru", "ky", "uz"] = "ru"


class LoginRequest(_Request):
    email: Annotated[str, Field(min_length=1, max_length=_LOGIN_PASSWORD_MAX_LENGTH)]
    password: AnyPassword


class PasswordChangeRequest(_Request):
    current_password: AnyPassword
    new_password: NewPassword


class CredentialsRequest(_Request):
    """`POST /auth/credentials`: field rules as at registration (DEC-141, DEC-142)."""

    email: Email
    password: NewPassword


class PasswordForgotRequest(_Request):
    # Not validated as an address: the answer must not depend on it (DEC-108).
    email: Annotated[str, Field(min_length=1, max_length=320)]


class PasswordResetRequest(_Request):
    token: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: NewPassword


class AcceptedResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class MeResponse(BaseModel):
    """`GET /auth/me`; also the body of `GET/PATCH /users/me` (DEC-152 п. 9)."""

    id: uuid.UUID
    email: str | None
    full_name: str
    phone: str | None
    preferred_language: str
    roles: list[str]
    must_change_password: bool
    has_password: bool

    @classmethod
    def from_user(cls, user: CurrentUser) -> MeResponse:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            preferred_language=user.preferred_language,
            roles=sorted(user.roles),
            must_change_password=user.must_change_password,
            has_password=user.has_password,
        )
