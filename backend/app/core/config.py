"""Application settings loaded from environment variables.

Secrets are never hard-coded: required values (such as the database URL)
have no defaults and must come from the environment.
"""

import re
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

JWT_SECRET_MIN_LENGTH = 32
# Exact browser Origin value: scheme, host and optional port; no path,
# trailing slash, wildcard or "null".
_ORIGIN_PATTERN = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?")


class Settings(BaseSettings):
    # hide_input_in_errors: a validation error must never echo a secret.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

    # --- Application ---
    app_env: Literal["dev", "demo", "test"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"
    restaurant_timezone: str = "Asia/Bishkek"
    # Comma-separated allowlist; empty means CORS is disabled (single origin).
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Database (required, no default credentials) ---
    database_url: str

    # --- Auth (DEC-140) ---
    # Required, no default; at least 32 characters; never logged.
    jwt_secret_key: SecretStr
    # Comma-separated exact Origin values for /auth/refresh and /auth/logout.
    # Separate from CORS_ALLOWED_ORIGINS. Empty means every check fails.
    csrf_trusted_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Argon2id, RFC 9106 low-memory profile (argon2-cffi defaults).
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_cost_kib: int = Field(default=65536, ge=8)
    argon2_parallelism: int = Field(default=4, ge=1)

    # --- Values used from later stages (DEC-80, DEC-84, DEC-87, DEC-59) ---
    access_token_ttl_minutes: int = Field(default=15, gt=0)
    refresh_token_ttl_days: int = Field(default=30, gt=0)
    password_reset_token_ttl_minutes: int = Field(default=30, gt=0)
    telegram_link_token_ttl_minutes: int = Field(default=10, gt=0)
    rate_limit_login: str = "5/minute"
    rate_limit_password_forgot: str = "3/hour"  # noqa: S105 - a rate limit, not a secret
    rate_limit_authenticated: str = "120/minute"
    rate_limit_public: str = "60/minute"
    # In-memory counters (DEC-95); tests switch them off except where tested.
    rate_limit_enabled: bool = True

    # --- Telegram Mini App authentication (DEC-142, DEC-152, DEC-154) ---
    # Empty or missing token (also only whitespace) means Telegram is
    # disabled: the Mini App endpoints answer 409 TELEGRAM_DISABLED. Never
    # logged; only `telegram_bot_token_value` exposes it to the verifier.
    telegram_bot_token: SecretStr | None = None
    telegram_webapp_auth_max_age_seconds: int = Field(default=3600, gt=0)
    telegram_webapp_init_data_max_length: int = Field(default=4096, gt=0)
    telegram_webapp_clock_skew_seconds: int = Field(default=60, ge=0)
    # Shared by /auth/telegram/webapp and /register, per IP (DEC-154 п. 6).
    rate_limit_telegram_webapp: str = "5/minute"

    # --- E-mail (DEC-108): smtplib; Mailpit catches mail in dev/demo ---
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, gt=0, le=65535)
    smtp_from: str = "Food Delivery Osh <no-reply@food-delivery.local>"
    smtp_timeout_seconds: int = Field(default=10, gt=0)
    # Public URL of the frontend; reset links point there (no trailing slash).
    frontend_base_url: str = "http://localhost:5173"

    # --- Uploaded images (DEC-70, DATABASE_SCHEMA.md §4.5) ---
    # Directory of the media volume; files are served at /media.
    media_root: str = "/app/media"
    image_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    payment_timeout_minutes: int = Field(default=30, gt=0)
    # Background job of unpaid mock_card orders (DEC-84, DEC-149, §14.5).
    payment_timeout_check_interval_seconds: int = Field(default=60, gt=0)
    payment_timeout_batch_size: int = Field(default=50, gt=0, le=1000)
    idempotency_key_ttl_hours: int = Field(default=24, gt=0)

    # --- Worker (DEC-104) ---
    worker_heartbeat_interval_seconds: int = Field(default=10, gt=0)
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"  # noqa: S108 - container-local file

    @field_validator("cors_allowed_origins", "csrf_trusted_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("csrf_trusted_origins")
    @classmethod
    def _check_csrf_origins(cls, value: list[str]) -> list[str]:
        for origin in value:
            if not _ORIGIN_PATTERN.fullmatch(origin):
                raise ValueError(
                    "each CSRF trusted origin must look like scheme://host[:port] "
                    "(http or https, no path or trailing slash)"
                )
        return value

    @field_validator("frontend_base_url")
    @classmethod
    def _check_frontend_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?", value):
            raise ValueError("FRONTEND_BASE_URL must be an http(s) URL")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _check_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"must be at least {JWT_SECRET_MIN_LENGTH} characters long")
        return value

    @model_validator(mode="after")
    def _check_argon2_memory(self) -> Self:
        # Argon2 needs at least 8 KiB of memory per lane.
        if self.argon2_memory_cost_kib < 8 * self.argon2_parallelism:
            raise ValueError("ARGON2_MEMORY_COST_KIB must be at least 8 * ARGON2_PARALLELISM")
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.app_env != "demo"

    @property
    def telegram_bot_token_value(self) -> str | None:
        """The bot token, or None if Telegram is not configured."""
        if self.telegram_bot_token is None:
            return None
        token = self.telegram_bot_token.get_secret_value().strip()
        return token or None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
