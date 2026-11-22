"""Delivery zone of a point (DATABASE_SCHEMA.md §9.1, DEC-53, DEC-94, DEC-102).

PostGIS decides: only active zones, `ST_Covers(boundary, point)` (a point
on the boundary belongs to the zone). On a shared border the zone with the
lower `delivery_fee` wins, then the lower `id`, so the result is stable.
Coordinates come from the request; the frontend is never trusted for the
zone, the fee or the minimum.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.delivery.models import SRID_WGS84, DeliveryZone


@dataclass(frozen=True)
class ZoneMatch:
    id: uuid.UUID
    name: str
    delivery_fee: Decimal
    min_order_amount: Decimal


async def find_zone(
    session: AsyncSession, latitude: Decimal, longitude: Decimal
) -> ZoneMatch | None:
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), SRID_WGS84)
    row = (
        await session.execute(
            select(
                DeliveryZone.id,
                DeliveryZone.name,
                DeliveryZone.delivery_fee,
                DeliveryZone.min_order_amount,
            )
            .where(
                DeliveryZone.is_active,
                DeliveryZone.boundary.is_not(None),
                func.ST_Covers(DeliveryZone.boundary, point),
            )
            .order_by(DeliveryZone.delivery_fee, DeliveryZone.id)
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    return ZoneMatch(
        id=row.id,
        name=row.name,
        delivery_fee=row.delivery_fee,
        min_order_amount=row.min_order_amount,
    )
