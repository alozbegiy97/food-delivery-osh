"""Unified API error format (DEC-73, DEC-103).

Every error response has the shape::

    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}

Stack traces, SQL, file paths, secrets and submitted input values are never
returned to the client. Details of unexpected errors go to the logs only.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)

# Fallback developer-facing messages (Russian). The frontend shows localized
# text by `code` through i18next.
_HTTP_STATUS_CODES: dict[int, tuple[str, str]] = {
    401: ("UNAUTHORIZED", "Требуется авторизация"),
    403: ("FORBIDDEN", "Доступ запрещён"),
    404: ("NOT_FOUND", "Ресурс не найден"),
    405: ("METHOD_NOT_ALLOWED", "Метод не поддерживается"),
    422: ("VALIDATION_ERROR", "Проверьте данные"),
    429: ("RATE_LIMITED", "Слишком много запросов"),
}
_INTERNAL_ERROR = ("INTERNAL_ERROR", "Внутренняя ошибка сервера")
# DEC-115: only for 4xx HTTP errors without a dedicated catalog code.
# HTTP 5xx without a dedicated code always maps to INTERNAL_ERROR.
_FALLBACK_CLIENT_ERROR = ("HTTP_ERROR", "Ошибка запроса")
_REQUEST_LOCATIONS = {"body", "query", "path", "header", "cookie"}


class AppError(Exception):
    """Domain/application error mapped to the unified error format."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else [],
            "request_id": get_request_id(),
        }
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details),
        headers=headers,
    )


def internal_error_response() -> JSONResponse:
    code, message = _INTERNAL_ERROR
    return error_response(500, code, message)


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ())]
        if loc and loc[0] in _REQUEST_LOCATIONS:
            loc = loc[1:]
        # The submitted value (`input`) is deliberately not echoed back:
        # it may contain passwords or other sensitive data.
        details.append({"field": ".".join(loc), "message": str(err.get("msg", ""))})
    return details


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered only for AppError
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    return error_response(422, "VALIDATION_ERROR", "Проверьте данные", _validation_details(exc))


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    if exc.status_code >= 500:
        code, message = _INTERNAL_ERROR
    else:
        code, message = _HTTP_STATUS_CODES.get(exc.status_code, _FALLBACK_CLIENT_ERROR)
    return error_response(exc.status_code, code, message, headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    # Unexpected exceptions are handled by RequestContextMiddleware so that the
    # response still carries the request ID header.
