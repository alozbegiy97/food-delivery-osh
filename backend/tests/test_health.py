"""Healthcheck endpoint."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_session
from tests.conftest import UNREACHABLE_DATABASE_URL


async def test_health_reports_unavailable_database(app: FastAPI, client: httpx.AsyncClient) -> None:
    engine = create_async_engine(UNREACHABLE_DATABASE_URL)

    async def unreachable_session() -> AsyncIterator[AsyncSession]:
        async with async_sessionmaker(engine)() as session:
            yield session

    app.dependency_overrides[get_session] = unreachable_session
    try:
        response = await client.get("/api/v1/health")
    finally:
        await engine.dispose()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.db
@pytest.mark.usefixtures("migrated_test_db")
async def test_health_ok_with_postgis(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["postgis"]
