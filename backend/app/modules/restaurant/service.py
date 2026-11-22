"""Public restaurant info for `GET /restaurant` (API_SPECIFICATION.md §3)."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.restaurant.hours import DayHours, is_open_at, next_opening_at
from app.modules.restaurant.models import (
    RESTAURANT_SETTINGS_ID,
    RestaurantSettings,
    RestaurantWorkingHours,
)


class WorkingDayOut(BaseModel):
    weekday: int  # 0 = Monday … 6 = Sunday
    opens_at: str | None  # "HH:MM" in the restaurant time zone
    closes_at: str | None
    is_closed: bool


class RestaurantOut(BaseModel):
    name: str
    phone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    timezone: str
    min_order_amount: Decimal
    delivery_enabled: bool
    pickup_enabled: bool
    is_open_now: bool
    next_opening_at: datetime | None
    working_hours: list[WorkingDayOut]


class RestaurantNotConfiguredError(RuntimeError):
    """The settings row is missing: run `python -m app.seeds base`."""


def _hhmm(value) -> str | None:  # noqa: ANN001 - datetime.time | None
    return value.strftime("%H:%M") if value else None


async def get_restaurant(session: AsyncSession, *, now: datetime | None = None) -> RestaurantOut:
    settings = await session.scalar(
        select(RestaurantSettings).where(RestaurantSettings.id == RESTAURANT_SETTINGS_ID)
    )
    if settings is None:
        raise RestaurantNotConfiguredError("restaurant_settings row is missing")
    week = [
        DayHours(row.weekday, row.opens_at, row.closes_at, row.is_closed)
        for row in await session.scalars(
            select(RestaurantWorkingHours).order_by(RestaurantWorkingHours.weekday)
        )
    ]
    tz = ZoneInfo(settings.timezone)
    moment = now or datetime.now(UTC)
    return RestaurantOut(
        name=settings.restaurant_name,
        phone=settings.phone,
        address=settings.address,
        latitude=float(settings.latitude) if settings.latitude is not None else None,
        longitude=float(settings.longitude) if settings.longitude is not None else None,
        timezone=settings.timezone,
        min_order_amount=settings.min_order_amount,
        delivery_enabled=settings.delivery_enabled,
        pickup_enabled=settings.pickup_enabled,
        is_open_now=is_open_at(moment, week, tz),
        next_opening_at=next_opening_at(moment, week, tz),
        working_hours=[
            WorkingDayOut(
                weekday=day.weekday,
                opens_at=_hhmm(day.opens_at),
                closes_at=_hhmm(day.closes_at),
                is_closed=day.is_closed,
            )
            for day in week
        ],
    )
