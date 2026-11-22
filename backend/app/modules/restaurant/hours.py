"""Working hours (DEC-20, DEC-21, DEC-107; DATABASE_SCHEMA.md §10.2).

One interval per weekday (0 = Monday). If `closes_at < opens_at` the interval
runs past midnight and belongs to the day it opened. Times are compared in
the restaurant time zone. Pure functions, no database access.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DayHours:
    weekday: int
    opens_at: time | None
    closes_at: time | None
    is_closed: bool


def _interval(day: date, hours: DayHours | None, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    if hours is None or hours.is_closed or hours.opens_at is None or hours.closes_at is None:
        return None
    start = datetime.combine(day, hours.opens_at, tzinfo=tz)
    end_day = day if hours.closes_at > hours.opens_at else day + timedelta(days=1)
    end = datetime.combine(end_day, hours.closes_at, tzinfo=tz)
    return start, end


def _by_weekday(week: list[DayHours]) -> dict[int, DayHours]:
    return {day.weekday: day for day in week}


def is_open_at(moment: datetime, week: list[DayHours], tz: ZoneInfo) -> bool:
    """True if `moment` (timezone-aware) falls into today's interval or into
    yesterday's interval that runs past midnight."""
    local = moment.astimezone(tz)
    days = _by_weekday(week)
    for offset in (0, -1):
        day = local.date() + timedelta(days=offset)
        interval = _interval(day, days.get(day.weekday()), tz)
        if interval and interval[0] <= local < interval[1]:
            return True
    return False


def next_opening_at(moment: datetime, week: list[DayHours], tz: ZoneInfo) -> datetime | None:
    """Start of the next interval after `moment`; None if open now or never."""
    if is_open_at(moment, week, tz):
        return None
    local = moment.astimezone(tz)
    days = _by_weekday(week)
    for offset in range(0, 8):
        day = local.date() + timedelta(days=offset)
        interval = _interval(day, days.get(day.weekday()), tz)
        if interval and interval[0] > local:
            return interval[0]
    return None
