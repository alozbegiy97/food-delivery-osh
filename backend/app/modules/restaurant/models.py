"""Restaurant settings and working hours (DATABASE_SCHEMA.md §10).

Structure only. Values of the single settings row and the weekly hours are
inserted by the `base` seed (DEC-117…DEC-119, DEC-124, DEC-125), not here.
Business rules (minimum order selection, overnight intervals, overlap of
the overnight tail with the next day) live in the service layer.
"""

from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import Coordinate, Money

RESTAURANT_SETTINGS_ID = 1  # singleton row (DATABASE_SCHEMA.md §10.1)


class RestaurantSettings(Base):
    __tablename__ = "restaurant_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    restaurant_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    longitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    min_order_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    delivery_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    pickup_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Bishkek")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(f"id = {RESTAURANT_SETTINGS_ID}", name="singleton"),
        CheckConstraint("min_order_amount >= 0", name="min_order_amount_non_negative"),
    )


class RestaurantWorkingHours(UUIDPrimaryKeyMixin, Base):
    """One interval per weekday (DEC-107); 0 = Monday … 6 = Sunday."""

    __tablename__ = "restaurant_working_hours"

    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False, unique=True)
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint(
            "is_closed OR (opens_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND opens_at <> closes_at)",
            name="open_day_interval",
        ),
    )
