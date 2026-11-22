"""Unified error format (DEC-73, DEC-103)."""

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.core.errors import AppError


def _assert_error_shape(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert "details" in error
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


async def test_unknown_path_returns_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    _assert_error_shape(response, 404, "NOT_FOUND")


async def test_wrong_method_returns_method_not_allowed(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/health")
    _assert_error_shape(response, 405, "METHOD_NOT_ALLOWED")


async def test_validation_error_does_not_echo_input(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def needs_int(limit: int) -> dict[str, int]:
        return {"limit": limit}

    app.add_api_route("/api/v1/_test/validation", needs_int)

    response = await client.get("/api/v1/_test/validation", params={"limit": "secret-value"})

    error = _assert_error_shape(response, 422, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "limit"
    assert "secret-value" not in response.text


async def test_app_error_is_rendered(app: FastAPI, client: httpx.AsyncClient) -> None:
    async def conflict() -> None:
        raise AppError(409, "PRICE_CHANGED", "Цена изменилась", details={"total": "10.00"})

    app.add_api_route("/api/v1/_test/app-error", conflict)

    response = await client.get("/api/v1/_test/app-error")

    error = _assert_error_shape(response, 409, "PRICE_CHANGED")
    assert error["details"] == {"total": "10.00"}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (418, "HTTP_ERROR"),  # no dedicated catalog code -> fallback (DEC-115)
        (422, "VALIDATION_ERROR"),  # fallback must not replace catalog codes
        (429, "RATE_LIMITED"),
        (502, "INTERNAL_ERROR"),  # 5xx without own code -> INTERNAL_ERROR
    ],
)
async def test_http_exception_codes(
    app: FastAPI, client: httpx.AsyncClient, status: int, code: str
) -> None:
    async def raise_http() -> None:
        raise HTTPException(status_code=status)

    app.add_api_route("/api/v1/_test/http", raise_http)

    response = await client.get("/api/v1/_test/http")

    _assert_error_shape(response, status, code)


async def test_unexpected_error_hides_details(app: FastAPI, client: httpx.AsyncClient) -> None:
    async def boom() -> None:
        raise RuntimeError("password=hunter2 at /srv/app/secret.py")

    app.add_api_route("/api/v1/_test/boom", boom)

    response = await client.get("/api/v1/_test/boom")

    _assert_error_shape(response, 500, "INTERNAL_ERROR")
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert "secret.py" not in response.text
