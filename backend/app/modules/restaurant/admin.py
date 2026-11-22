"""Restaurant settings and working hours for the administrator (API §9
"Staff/settings"; DATABASE_SCHEMA.md §10; DEC-21, DEC-107, DEC-150).

- settings: name, phone (DEC-89 normalization), address, coordinates (both or
  none), minimum order, delivery/pickup flags; the time zone `Asia/Bishkek`
  is read-only (DEC-150);
- working hours: exactly 7 days, one interval per day, `is_closed` or
  `opens_at != closes_at`; an overnight interval (`closes_at < opens_at`)
  belongs to its opening day and its tail must not overlap the next day's
  interval; the whole week is replaced atomically; violations ->
  `422 INVALID_WORKING_HOURS` with details.
"""

from datetime import time
from decimal import Decimal
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.phone import normalize_phone
from app.modules.addresses.schemas import Latitude, Longitude
from app.modules.admin_catalog.schemas import Money  # 0..max, 2 decimals, quantized
from app.modules.restaurant.models import (
    RESTAURANT_SETTINGS_ID,
    RestaurantSettings,
    RestaurantWorkingHours,
)

MAX_NAME = 180
MAX_ADDRESS = 500


def _text(limit: int, required: bool):  # noqa: ANN202 - validator
    def validate(value: str | None) -> str | None:
        if value is None:
            if required:
                raise ValueError("обязательное поле")
            return None
        cleaned = value.strip()
        if required and not cleaned:
            raise ValueError("обязательное поле")
        if len(cleaned) > limit:
            raise ValueError(f"не более {limit} символов")
        return cleaned or None

    return validate


def _phone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return normalize_phone(value)


class SettingsOut(BaseModel):
    restaurant_name: str
    phone: str | None
    address: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    min_order_amount: Decimal
    delivery_enabled: bool
    pickup_enabled: bool
    timezone: str


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # `timezone` is not accepted

    restaurant_name: Annotated[
        str | None, Field(max_length=MAX_NAME * 2), AfterValidator(_text(MAX_NAME, False))
    ] = None
    phone: Annotated[str | None, Field(max_length=40), AfterValidator(_phone)] = None
    address: Annotated[
        str | None, Field(max_length=MAX_ADDRESS * 2), AfterValidator(_text(MAX_ADDRESS, False))
    ] = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    min_order_amount: Money | None = None
    delivery_enabled: bool | None = None
    pickup_enabled: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        fields = self.model_fields_set
        if not fields:
            raise ValueError("укажите хотя бы одно поле")
        for name in ("restaurant_name", "min_order_amount", "delivery_enabled", "pickup_enabled"):
            if name in fields and getattr(self, name) is None:
                raise ValueError(f"{name} не может быть пустым")
        if ("latitude" in fields) != ("longitude" in fields) or (
            (self.latitude is None) != (self.longitude is None)
        ):
            raise ValueError("latitude и longitude указываются вместе")
        return self


class DayHoursIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: Annotated[int, Field(ge=0, le=6)]  # 0 = Monday
    is_closed: bool
    opens_at: time | None = None
    closes_at: time | None = None


class DayHoursOut(BaseModel):
    weekday: int
    is_closed: bool
    opens_at: time | None
    closes_at: time | None


class WeekHours(BaseModel):
    items: list[DayHoursOut]


class WeekHoursIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[DayHoursIn], Field(min_length=7, max_length=7)]


async def _settings_row(session: AsyncSession) -> RestaurantSettings:
    row = await session.scalar(
        select(RestaurantSettings).where(RestaurantSettings.id == RESTAURANT_SETTINGS_ID)
    )
    if row is None:
        raise AppError(404, "NOT_FOUND", "Ресурс не найден")
    return row


def _settings_out(row: RestaurantSettings) -> SettingsOut:
    return SettingsOut(
        restaurant_name=row.restaurant_name,
        phone=row.phone,
        address=row.address,
        latitude=row.latitude,
        longitude=row.longitude,
        min_order_amount=row.min_order_amount,
        delivery_enabled=row.delivery_enabled,
        pickup_enabled=row.pickup_enabled,
        timezone=row.timezone,
    )


async def get_settings_admin(session: AsyncSession) -> SettingsOut:
    return _settings_out(await _settings_row(session))


async def update_settings(session: AsyncSession, payload: SettingsUpdate) -> SettingsOut:
    await _settings_row(session)
    changes = payload.model_dump(include=payload.model_fields_set)
    await session.execute(
        update(RestaurantSettings)
        .where(RestaurantSettings.id == RESTAURANT_SETTINGS_ID)
        .values(**changes)
    )
    await session.commit()
    return _settings_out(await _settings_row(session))


# --------------------------------------------------------------------------
# Working hours
# --------------------------------------------------------------------------


async def get_hours(session: AsyncSession) -> WeekHours:
    rows = await session.scalars(
        select(RestaurantWorkingHours).order_by(RestaurantWorkingHours.weekday)
    )
    return WeekHours(
        items=[
            DayHoursOut(
                weekday=r.weekday, is_closed=r.is_closed, opens_at=r.opens_at, closes_at=r.closes_at
            )
            for r in rows
        ]
    )


def _invalid(details: list[dict[str, object]]) -> AppError:
    return AppError(422, "INVALID_WORKING_HOURS", "Проверьте рабочие часы", details=details)


def validate_week(days: list[DayHoursIn]) -> list[DayHoursIn]:
    """DEC-107 rules; returns the week sorted by weekday."""
    problems: list[dict[str, object]] = []
    by_day = {d.weekday: d for d in days}
    if sorted(by_day) != list(range(7)):
        raise _invalid([{"weekday": None, "problem": "each_weekday_once"}])
    for day in by_day.values():
        if day.is_closed:
            continue
        if day.opens_at is None or day.closes_at is None:
            problems.append({"weekday": day.weekday, "problem": "times_required"})
        elif day.opens_at == day.closes_at:
            problems.append({"weekday": day.weekday, "problem": "same_times"})
    if not problems:
        for weekday, day in by_day.items():
            if day.is_closed or day.opens_at is None or day.closes_at is None:
                continue
            if day.closes_at < day.opens_at:  # overnight: tail on the next day
                nxt = by_day[(weekday + 1) % 7]
                if not nxt.is_closed and nxt.opens_at is not None and nxt.opens_at < day.closes_at:
                    problems.append({"weekday": weekday, "problem": "overnight_overlaps_next_day"})
    if problems:
        raise _invalid(problems)
    return [by_day[i] for i in range(7)]


async def replace_hours(session: AsyncSession, payload: WeekHoursIn) -> WeekHours:
    week = validate_week(payload.items)
    # Lock the rows of the week: one replacement at a time.
    await session.execute(select(RestaurantWorkingHours.id).with_for_update())
    for day in week:
        values = {
            "is_closed": day.is_closed,
            "opens_at": None if day.is_closed else day.opens_at,
            "closes_at": None if day.is_closed else day.closes_at,
        }
        result = await session.execute(
            update(RestaurantWorkingHours)
            .where(RestaurantWorkingHours.weekday == day.weekday)
            .values(**values)
        )
        if result.rowcount == 0:
            session.add(RestaurantWorkingHours(weekday=day.weekday, **values))
    await session.commit()
    return await get_hours(session)
