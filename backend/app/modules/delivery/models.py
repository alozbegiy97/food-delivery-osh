"""Delivery zones, deliveries and courier assignments (DATABASE_SCHEMA.md §9).

`delivery_zones` belongs to revision 0003 (DEC-116); `deliveries` and
`courier_assignments` are created in revision 0007. The demo zone is
inserted by the `demo` seed (DEC-119, DEC-124).

Geometry is `geometry(MultiPolygon, 4326)`; validity is guaranteed by the
CHECK below (DEC-122) in addition to service-level validation. Overlap of
active zones (DEC-53) and point-in-zone selection (DEC-102) are service
rules and are not expressed as constraints here.

Assignment rules live in the service layer (DEC-48…DEC-52, DEC-67, DEC-83,
DEC-91, DEC-92): eligible orders, courier role/profile/limit checks with
`SELECT … FOR UPDATE`, decline only before acceptance, reassignment and
completion. The database enforces one active assignment per order and
the `declined` consistency CHECKs of §9.3.
Relationships use `lazy="raise"`: load them explicitly (DEC-121).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import Money, sql_in
from app.modules.delivery.enums import AssignmentStatus, AssignmentType
from app.modules.orders.models import Order
from app.modules.users.models import User

SRID_WGS84 = 4326


class DeliveryZone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "delivery_zones"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    delivery_fee: Mapped[Decimal] = mapped_column(Money, nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # NULL until the zone is drawn. The GIST index is declared explicitly
    # below (spatial_index=False) so it follows the project naming convention.
    boundary: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_delivery_zones_boundary", "boundary", postgresql_using="gist"),
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_non_negative"),
        CheckConstraint("min_order_amount >= 0", name="min_order_amount_non_negative"),
        # An active zone must have a boundary (DATABASE_SCHEMA.md §9.1, D5).
        CheckConstraint("NOT is_active OR boundary IS NOT NULL", name="active_requires_boundary"),
        # NULL is allowed; a present geometry must be valid (DEC-122).
        CheckConstraint("boundary IS NULL OR ST_IsValid(boundary)", name="boundary_valid"),
    )


class Delivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Operational delivery data; address and fee live in the order snapshot (DEC-16)."""

    __tablename__ = "deliveries"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    delivery_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_zones.id", ondelete="SET NULL")
    )
    delivery_comment: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="delivery", lazy="raise")
    zone: Mapped[DeliveryZone | None] = relationship(lazy="raise")

    __table_args__ = (
        Index("ix_deliveries_delivery_zone_id", "delivery_zone_id"),  # DEC-134
    )


class CourierAssignment(UUIDPrimaryKeyMixin, Base):
    """Assignment history of an order; no created_at/updated_at by design (§9.3)."""

    __tablename__ = "courier_assignments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    courier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL for automatic assignment or after the admin account is deleted.
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assignment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AssignmentStatus.ACTIVE.value
    )
    # No default: the service sets it explicitly (§9.3).
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set only when the courier actually accepts (DEC-52, DEC-83).
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # DEC-92
    decline_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="courier_assignments", lazy="raise")
    courier: Mapped[User] = relationship(foreign_keys=[courier_id], lazy="raise")
    assigner: Mapped[User | None] = relationship(foreign_keys=[assigned_by], lazy="raise")

    __table_args__ = (
        # One active assignment per order (§9.3).
        Index(
            "uq_courier_assignments_order_id_active",
            "order_id",
            unique=True,
            postgresql_where=text(f"status = '{AssignmentStatus.ACTIVE}'"),
        ),
        Index("ix_courier_assignments_courier_id_status", "courier_id", "status"),
        Index("ix_courier_assignments_order_id_courier_id", "order_id", "courier_id"),
        Index("ix_courier_assignments_assigned_by", "assigned_by"),  # DEC-134
        CheckConstraint(sql_in("assignment_type", AssignmentType), name="assignment_type"),
        CheckConstraint(sql_in("status", AssignmentStatus), name="status"),
        CheckConstraint(
            "(status = 'declined') = (declined_at IS NOT NULL)",
            name="declined_at_matches_status",
        ),
        CheckConstraint(
            "status <> 'declined' OR accepted_at IS NULL", name="declined_not_accepted"
        ),
    )
