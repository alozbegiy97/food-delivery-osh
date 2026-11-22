"""Working hours: open now and next opening (DEC-20, DEC-21, DEC-107)."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.modules.restaurant.hours import DayHours, is_open_at, next_opening_at

TZ = ZoneInfo("Asia/Bishkek")  # UTC+6, no DST


def _week(opens: str, closes: str, closed_days: tuple[int, ...] = ()) -> list[DayHours]:
    o, c = time.fromisoformat(opens), time.fromisoformat(closes)
    return [
        DayHours(
            day,
            None if day in closed_days else o,
            None if day in closed_days else c,
            day in closed_days,
        )
        for day in range(7)
    ]


def _local(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def test_daytime_interval() -> None:
    week = _week("10:00", "22:00")
    assert is_open_at(_local("2026-11-11 10:00"), week, TZ)  # opening minute included
    assert is_open_at(_local("2026-11-11 21:59"), week, TZ)
    assert not is_open_at(_local("2026-11-11 22:00"), week, TZ)  # closing minute excluded
    assert not is_open_at(_local("2026-11-11 09:59"), week, TZ)


def test_overnight_interval_belongs_to_opening_day() -> None:
    week = _week("18:00", "02:00")
    assert is_open_at(_local("2026-11-11 23:30"), week, TZ)
    assert is_open_at(_local("2026-11-12 01:59"), week, TZ)  # tail of Wednesday
    assert not is_open_at(_local("2026-11-12 02:00"), week, TZ)


def test_overnight_tail_of_closed_next_day_still_counts() -> None:
    # 2026-11-11 is a Wednesday (2); Thursday (3) is closed.
    week = _week("18:00", "02:00", closed_days=(3,))
    assert is_open_at(_local("2026-11-12 01:00"), week, TZ)  # Wednesday's tail
    assert not is_open_at(_local("2026-11-12 19:00"), week, TZ)


def test_next_opening() -> None:
    week = _week("10:00", "22:00", closed_days=(3,))
    assert next_opening_at(_local("2026-11-11 12:00"), week, TZ) is None  # open now
    assert next_opening_at(_local("2026-11-11 08:00"), week, TZ) == _local("2026-11-11 10:00")
    # Wednesday evening -> Thursday closed -> Friday 10:00.
    assert next_opening_at(_local("2026-11-11 23:00"), week, TZ) == _local("2026-11-13 10:00")


def test_moment_in_other_time_zone_is_converted() -> None:
    week = _week("10:00", "22:00")
    # 04:30 UTC = 10:30 in Bishkek.
    assert is_open_at(datetime(2026, 11, 11, 4, 30, tzinfo=UTC), week, TZ)


def test_all_days_closed() -> None:
    week = _week("10:00", "22:00", closed_days=tuple(range(7)))
    assert not is_open_at(_local("2026-11-11 12:00"), week, TZ)
    assert next_opening_at(_local("2026-11-11 12:00"), week, TZ) is None
