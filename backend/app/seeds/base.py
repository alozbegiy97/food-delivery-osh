"""Seed mode `base`: required system records (DEC-117, DEC-136, DEC-137).

Roles, payment methods, the single `restaurant_settings` row and weekly
working hours. These are system records without UUIDv5: an existing row
is recognised by its natural key and skipped without changes, a missing
one is created. Users are never created (DEC-88, DEC-113).
"""

from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.payments.enums import PaymentMethodCode
from app.modules.payments.models import PaymentMethod
from app.modules.restaurant.models import (
    RESTAURANT_SETTINGS_ID,
    RestaurantSettings,
    RestaurantWorkingHours,
)
from app.modules.users.enums import RoleName
from app.modules.users.models import Role
from app.seeds.common import SeedReport, insert_missing, prepare_seed

# Exactly four roles, description NULL (DEC-136).
ROLE_ROWS: list[dict[str, Any]] = [{"name": role.value, "description": None} for role in RoleName]

# cash first, mock_card second; both active. mock_card is a demo-only
# method that never charges money (DEC-47). Names live in frontend i18n.
PAYMENT_METHOD_ROWS: list[dict[str, Any]] = [
    {"code": PaymentMethodCode.CASH.value, "is_active": True, "sort_order": 0},
    {"code": PaymentMethodCode.MOCK_CARD.value, "is_active": True, "sort_order": 1},
]

# DEC-118 and DEC-125: fictitious demo values, explicitly marked as demo.
# Coordinates are not filled; other columns use the schema defaults
# (delivery/pickup enabled, timezone Asia/Bishkek).
RESTAURANT_SETTINGS_ROW: dict[str, Any] = {
    "id": RESTAURANT_SETTINGS_ID,
    "restaurant_name": "Demo Restaurant — Osh",
    "phone": "+996000000000",
    "address": "Демонстрационный адрес, г. Ош",
    "latitude": None,
    "longitude": None,
    "min_order_amount": Decimal("300.00"),
}

# Every day 10:00-23:00 Asia/Bishkek (DEC-124); weekday 0 = Monday.
OPENS_AT = time(10, 0)
CLOSES_AT = time(23, 0)
WORKING_HOURS_ROWS: list[dict[str, Any]] = [
    {"weekday": weekday, "opens_at": OPENS_AT, "closes_at": CLOSES_AT, "is_closed": False}
    for weekday in range(7)
]


async def seed_base(conn: AsyncConnection) -> SeedReport:
    """Create missing `base` records in the caller's transaction (no commit)."""
    report = SeedReport()
    await prepare_seed(conn)
    await insert_missing(conn, report, Role, ROLE_ROWS)
    await insert_missing(conn, report, PaymentMethod, PAYMENT_METHOD_ROWS)
    await insert_missing(conn, report, RestaurantSettings, [RESTAURANT_SETTINGS_ROW])
    await insert_missing(conn, report, RestaurantWorkingHours, WORKING_HOURS_ROWS)
    return report
