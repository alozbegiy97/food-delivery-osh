"""Rate limits (DEC-80, DEC-95; API_SPECIFICATION.md §1.2).

Values come from the settings. Counters live in memory of the single API
process (DEC-95), in the storage and strategy of a `slowapi.Limiter`.

- Every API request: 120/minute per authenticated user (valid access token),
  otherwise 60/minute per client IP. Applied by `RateLimitMiddleware`.
- `POST /auth/login`: additionally 5/minute per IP (`login_rate_limit`);
  `POST /auth/telegram/webapp/link` spends the same counter (DEC-152 п. 4).
- `POST /auth/telegram/webapp` and `/register`: one shared separate counter,
  RATE_LIMIT_TELEGRAM_WEBAPP per IP (`telegram_webapp_rate_limit`, DEC-154).
- `POST /auth/password/forgot` never answers 429: its own 3/hour limit per
  e-mail and per IP is checked inside the endpoint, which still answers 202
  but sends nothing (DEC-108). The middleware skips this path.
- Exceeded limits answer `429 RATE_LIMITED` with `Retry-After`.

A limiter is created per application (`create_app`), so tests never share
counters.
"""

import math
import time

from fastapi import Request
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.core.errors import AppError, error_response
from app.core.security import InvalidAccessTokenError, decode_access_token


class RateLimiter:
    """Thin wrapper over the slowapi limiter storage and strategy."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._limiter = Limiter(
            key_func=get_remote_address, storage_uri="memory://", enabled=enabled
        )

    def hit(self, rate: str, *identifiers: str) -> int | None:
        """Count one request. Returns None if allowed, else seconds to wait."""
        if not self.enabled:
            return None
        item = parse(rate)
        strategy = self._limiter.limiter
        if strategy.hit(item, *identifiers):
            return None
        reset_at = strategy.get_window_stats(item, *identifiers).reset_time
        return max(1, math.ceil(reset_at - time.time()))


def client_ip(request: Request) -> str:
    return get_remote_address(request) or "unknown"


def rate_limited(retry_after: int) -> AppError:
    return AppError(
        429,
        "RATE_LIMITED",
        "Слишком много запросов, попробуйте позже",
        headers={"Retry-After": str(retry_after)},
    )


def _limiter_of(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


async def login_rate_limit(request: Request) -> None:
    """FastAPI dependency for `POST /auth/login`: 5/minute per IP."""
    retry_after = _limiter_of(request).hit(
        get_settings().rate_limit_login, "login", client_ip(request)
    )
    if retry_after is not None:
        raise rate_limited(retry_after)


async def telegram_webapp_rate_limit(request: Request) -> None:
    """FastAPI dependency for `/auth/telegram/webapp` and `/register` (shared)."""
    retry_after = _limiter_of(request).hit(
        get_settings().rate_limit_telegram_webapp, "telegram-webapp", client_ip(request)
    )
    if retry_after is not None:
        raise rate_limited(retry_after)


def forgot_allowed(request: Request, email: str) -> bool:
    """3/hour per e-mail and per IP; both counters are always advanced."""
    limiter = _limiter_of(request)
    rate = get_settings().rate_limit_password_forgot
    by_email = limiter.hit(rate, "forgot-email", email)
    by_ip = limiter.hit(rate, "forgot-ip", client_ip(request))
    return by_email is None and by_ip is None


def _bearer_subject(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() != "bearer" or not token:
                return None
            try:
                return str(decode_access_token(token.strip()))
            except InvalidAccessTokenError:
                return None
    return None


class RateLimitMiddleware:
    """Global per-user / per-IP limit for every request under the API prefix."""

    def __init__(self, app: ASGIApp, *, limiter: RateLimiter, exempt_paths: set[str]) -> None:
        self.app = app
        self.limiter = limiter
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not self.limiter.enabled
            or not path.startswith(settings.api_prefix)
            or path in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return
        subject = _bearer_subject(scope)
        if subject is not None:
            retry_after = self.limiter.hit(settings.rate_limit_authenticated, "user", subject)
        else:
            request = Request(scope)
            retry_after = self.limiter.hit(settings.rate_limit_public, "ip", client_ip(request))
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        error = rate_limited(retry_after)
        response = error_response(error.status_code, error.code, error.message, None, error.headers)
        await response(scope, receive, send)
