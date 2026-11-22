"""Application factory settings."""

import httpx

from app.core.config import Settings
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL


async def _status(settings: Settings, path: str) -> int:
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get(path)).status_code


async def test_api_docs_available_in_dev() -> None:
    settings = Settings(app_env="dev", database_url=UNREACHABLE_DATABASE_URL)
    assert await _status(settings, "/api/v1/openapi.json") == 200


async def test_api_docs_disabled_in_demo() -> None:
    settings = Settings(app_env="demo", database_url=UNREACHABLE_DATABASE_URL)
    assert await _status(settings, "/api/v1/openapi.json") == 404
    assert await _status(settings, "/api/v1/docs") == 404


def test_cors_origins_are_parsed_from_comma_separated_env() -> None:
    settings = Settings(
        database_url=UNREACHABLE_DATABASE_URL,
        cors_allowed_origins=" http://a.test , http://b.test ,",
    )
    assert settings.cors_allowed_origins == ["http://a.test", "http://b.test"]
