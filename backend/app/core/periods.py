"""Calendar periods of the restaurant (DEC-90, DEC-114; API §9 "Dashboard").

`date_from` and `date_to` are calendar dates in Asia/Bishkek, both inclusive;
internally the half-open interval [00:00 date_from, 00:00 of the day after
date_to) in Asia/Bishkek is converted to UTC, so the last day is never lost.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import AppError

RESTAURANT_TZ = ZoneInfo("Asia/Bishkek")
DEFAULT_DAYS = 7  # today and the 6 previous days (DEC-114)


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive

    def days(self) -> list[date]:
        count = (self.date_to - self.date_from).days + 1
        return [self.date_from + timedelta(days=i) for i in range(count)]


def today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(RESTAURANT_TZ).date()


def make_period(
    date_from: date | None, date_to: date | None, *, now: datetime | None = None
) -> Period:
    """Inclusive local dates -> UTC bounds; defaults to the last 7 days."""
    if date_to is None:
        date_to = today(now) if date_from is None else max(date_from, today(now))
    if date_from is None:
        date_from = date_to - timedelta(days=DEFAULT_DAYS - 1)
    if date_from > date_to:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Проверьте данные",
            details=[{"field": "date_from", "message": "date_from позже date_to"}],
        )
    start = datetime.combine(date_from, time.min, tzinfo=RESTAURANT_TZ).astimezone(UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=RESTAURANT_TZ).astimezone(
        UTC
    )
    return Period(date_from, date_to, start, end)
