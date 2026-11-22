"""X-Request-ID handling."""

import re

import httpx

_GENERATED = re.compile(r"^[0-9a-f]{32}$")


async def test_valid_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/missing", headers={"X-Request-ID": "abc-123.DEF_4"})
    assert response.headers["X-Request-ID"] == "abc-123.DEF_4"
    assert response.json()["error"]["request_id"] == "abc-123.DEF_4"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/missing")
    assert _GENERATED.fullmatch(response.headers["X-Request-ID"])


async def test_invalid_incoming_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/missing", headers={"X-Request-ID": "bad id <script>"})
    assert _GENERATED.fullmatch(response.headers["X-Request-ID"])
