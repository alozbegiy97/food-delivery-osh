"""Healthcheck: confirms the API process and database (with PostGIS) are reachable."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

_DB_TIMEOUT_SECONDS = 3


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok"]
    # PostGIS version, or null if the extension is not installed yet
    # (the first Alembic migration installs it).
    postgis: str | None


@router.get("/health", response_model=HealthResponse)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    try:
        async with asyncio.timeout(_DB_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
            postgis = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("Healthcheck: database unavailable (%s)", type(exc).__name__)
        raise AppError(503, "SERVICE_UNAVAILABLE", "База данных недоступна") from exc

    return HealthResponse(
        status="ok" if postgis else "degraded",
        database="ok",
        postgis=postgis,
    )
