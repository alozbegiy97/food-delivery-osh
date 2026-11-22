"""Delivery zones for the administrator (API §9; DATABASE_SCHEMA.md §9.1;
DEC-53, DEC-94, DEC-102, DEC-122, DEC-150).

- GeoJSON `Polygon` or `MultiPolygon`, SRID 4326 (a `crs` member with another
  SRID is refused); stored always as `MultiPolygon` (`ST_Multi`);
- PostGIS decides: `ST_IsValid` (else `422 INVALID_GEOMETRY` with the
  reason), and active zones must not overlap by their interiors
  (`ST_Relate(a, b, 'T********')`, touching along a border is allowed;
  `422 ZONE_OVERLAP` with the names of the other zones) — checked on create,
  on geometry change and on (re)activation;
- `DELETE` deactivates (`is_active = false`), never deletes physically;
- every change takes a transaction-level advisory lock, so two parallel
  edits cannot both pass the overlap check.
"""

import json
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.admin_catalog.schemas import Money  # 0..max, 2 decimals, quantized
from app.modules.delivery.models import SRID_WGS84, DeliveryZone

# Advisory lock key of zone edits (any constant unique in the project).
ZONE_LOCK_KEY = 0x5A_4F_4E_45  # "ZONE"
MAX_NAME = 120
MAX_DESCRIPTION = 500


class GeoJsonGeometry(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class ZoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION)] = None
    delivery_fee: Money
    min_order_amount: Money = Decimal("0")
    is_active: bool = True
    boundary: GeoJsonGeometry

    @model_validator(mode="after")
    def _clean(self) -> Self:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name обязателен")
        self.description = (self.description or "").strip() or None
        return self


class ZoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=MAX_NAME)] = None
    description: Annotated[str | None, Field(max_length=MAX_DESCRIPTION)] = None
    delivery_fee: Money | None = None
    min_order_amount: Money | None = None
    is_active: bool | None = None
    boundary: GeoJsonGeometry | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        fields = self.model_fields_set
        if not fields:
            raise ValueError("укажите хотя бы одно поле")
        for name in ("name", "delivery_fee", "min_order_amount", "is_active", "boundary"):
            if name in fields and getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name обязателен")
        if "description" in fields:
            self.description = (self.description or "").strip() or None
        return self


class AdminZoneOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    delivery_fee: Decimal
    min_order_amount: Decimal
    is_active: bool
    # GeoJSON MultiPolygon or null (a zone not drawn yet).
    boundary: dict[str, Any] | None


class AdminZoneList(BaseModel):
    items: list[AdminZoneOut]


def _geometry_error(reason: str) -> AppError:
    return AppError(
        422,
        "INVALID_GEOMETRY",
        "Некорректная геометрия зоны",
        details=[{"field": "boundary", "message": reason}],
    )


def _not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


async def _lock(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ZONE_LOCK_KEY})


async def _geometry(session: AsyncSession, geojson: GeoJsonGeometry) -> Any:
    """Validated MultiPolygon expression of the request geometry."""
    raw = json.dumps(geojson.model_dump())
    try:
        row = (
            await session.execute(
                select(
                    func.ST_SRID(func.ST_GeomFromGeoJSON(raw)).label("srid"),
                    func.ST_IsValid(func.ST_GeomFromGeoJSON(raw)).label("valid"),
                    func.ST_IsValidReason(func.ST_GeomFromGeoJSON(raw)).label("reason"),
                    func.ST_IsEmpty(func.ST_GeomFromGeoJSON(raw)).label("empty"),
                    func.ST_XMin(func.ST_GeomFromGeoJSON(raw)).label("xmin"),
                    func.ST_XMax(func.ST_GeomFromGeoJSON(raw)).label("xmax"),
                    func.ST_YMin(func.ST_GeomFromGeoJSON(raw)).label("ymin"),
                    func.ST_YMax(func.ST_GeomFromGeoJSON(raw)).label("ymax"),
                )
            )
        ).one()
    except Exception:  # malformed GeoJSON: PostGIS raises
        await session.rollback()
        raise _geometry_error("GeoJSON не разобран") from None
    if row.srid not in (0, SRID_WGS84):
        raise _geometry_error("SRID должен быть 4326")
    if row.empty:
        raise _geometry_error("пустая геометрия")
    if row.xmin < -180 or row.xmax > 180 or row.ymin < -90 or row.ymax > 90:
        raise _geometry_error("координаты вне диапазона (долгота, широта)")
    if not row.valid:
        raise _geometry_error(row.reason or "невалидная геометрия")
    return func.ST_Multi(func.ST_SetSRID(func.ST_GeomFromGeoJSON(raw), SRID_WGS84))


async def _check_overlap(session: AsyncSession, zone_id: uuid.UUID | None, geometry: Any) -> None:
    query = select(DeliveryZone.name).where(
        DeliveryZone.is_active,
        DeliveryZone.boundary.is_not(None),
        func.ST_Relate(DeliveryZone.boundary, geometry, "T********"),
    )
    if zone_id is not None:
        query = query.where(DeliveryZone.id != zone_id)
    names = list(await session.scalars(query.order_by(DeliveryZone.name)))
    if names:
        raise AppError(
            422,
            "ZONE_OVERLAP",
            "Зона пересекается с другой активной зоной",
            details=[{"field": "boundary", "message": name} for name in names],
        )


async def _out(session: AsyncSession, zone_id: uuid.UUID) -> AdminZoneOut:
    row = (
        await session.execute(
            select(DeliveryZone, func.ST_AsGeoJSON(DeliveryZone.boundary).label("geojson")).where(
                DeliveryZone.id == zone_id
            )
        )
    ).one_or_none()
    if row is None:
        raise _not_found()
    zone = row[0]
    return AdminZoneOut(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        delivery_fee=zone.delivery_fee,
        min_order_amount=zone.min_order_amount,
        is_active=zone.is_active,
        boundary=json.loads(row.geojson) if row.geojson else None,
    )


async def list_zones(session: AsyncSession) -> AdminZoneList:
    ids = list(
        await session.scalars(
            select(DeliveryZone.id).order_by(DeliveryZone.is_active.desc(), DeliveryZone.name)
        )
    )
    return AdminZoneList(items=[await _out(session, zone_id) for zone_id in ids])


async def create_zone(session: AsyncSession, payload: ZoneCreate) -> AdminZoneOut:
    await _lock(session)
    geometry = await _geometry(session, payload.boundary)
    if payload.is_active:
        await _check_overlap(session, None, geometry)
    zone_id = await session.scalar(
        DeliveryZone.__table__.insert()
        .values(
            name=payload.name,
            description=payload.description,
            delivery_fee=payload.delivery_fee,
            min_order_amount=payload.min_order_amount,
            is_active=payload.is_active,
            boundary=geometry,
        )
        .returning(DeliveryZone.id)
    )
    await session.commit()
    return await _out(session, zone_id)


async def update_zone(
    session: AsyncSession, zone_id: uuid.UUID, payload: ZoneUpdate
) -> AdminZoneOut:
    await _lock(session)
    zone = await session.scalar(
        select(DeliveryZone).where(DeliveryZone.id == zone_id).with_for_update()
    )
    if zone is None:
        raise _not_found()
    fields = payload.model_fields_set
    values: dict[str, Any] = {
        name: getattr(payload, name)
        for name in ("name", "description", "delivery_fee", "min_order_amount", "is_active")
        if name in fields
    }
    geometry = None
    if "boundary" in fields and payload.boundary is not None:
        geometry = await _geometry(session, payload.boundary)
        values["boundary"] = geometry
    active = values.get("is_active", zone.is_active)
    if active:
        if geometry is None:
            if zone.boundary is None:
                raise _geometry_error("у активной зоны должна быть граница")
            geometry = (
                select(DeliveryZone.boundary).where(DeliveryZone.id == zone_id).scalar_subquery()
            )
        await _check_overlap(session, zone_id, geometry)
    await session.execute(update(DeliveryZone).where(DeliveryZone.id == zone_id).values(**values))
    await session.commit()
    return await _out(session, zone_id)


async def deactivate_zone(session: AsyncSession, zone_id: uuid.UUID) -> AdminZoneOut:
    """DEC-150: `DELETE` = deactivation; orders keep their snapshots (DEC-16)."""
    await _lock(session)
    result = await session.execute(
        update(DeliveryZone).where(DeliveryZone.id == zone_id).values(is_active=False)
    )
    if result.rowcount == 0:
        await session.rollback()
        raise _not_found()
    await session.commit()
    return await _out(session, zone_id)
