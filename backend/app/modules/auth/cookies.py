"""Refresh-token cookie (DEC-68, DEC-140).

`refresh_token`: HttpOnly, SameSite=Strict, Path=<api prefix>/auth,
Max-Age = refresh token lifetime. `Secure` only when APP_ENV=demo.
"""

from fastapi import Response

from app.core.config import get_settings

REFRESH_COOKIE_NAME = "refresh_token"


def _attributes() -> dict[str, object]:
    settings = get_settings()
    return {
        "path": f"{settings.api_prefix}/auth",
        "httponly": True,
        "samesite": "strict",
        "secure": settings.app_env == "demo",
    }


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    max_age = get_settings().refresh_token_ttl_days * 24 * 60 * 60
    response.set_cookie(REFRESH_COOKIE_NAME, raw_token, max_age=max_age, **_attributes())


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, **_attributes())
