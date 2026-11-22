"""Restaurant settings, working hours, payment methods, delivery zones.

DATABASE_SCHEMA.md §10.1, §10.2, §8.1, §9.1; DEC-116, DEC-122.
Structure only: rows are inserted by the `base` / `demo` seed (DEC-117).

Revision ID: 0003_restaurant_delivery
Revises: 0002_users
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry

from alembic import op

revision: str = "0003_restaurant_delivery"
down_revision: str | None = "0002_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=UUID_PK, nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def upgrade() -> None:
    # §10.1 — single row with the settings of the only branch.
    op.create_table(
        "restaurant_settings",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("restaurant_name", sa.String(length=180), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column(
            "min_order_amount",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("delivery_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("pickup_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Bishkek", nullable=False),
        _updated_at(),
        sa.CheckConstraint("id = 1", name=op.f("ck_restaurant_settings_singleton")),
        sa.CheckConstraint(
            "min_order_amount >= 0",
            name=op.f("ck_restaurant_settings_min_order_amount_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restaurant_settings")),
    )

    # §10.2 — one interval per weekday (DEC-107), 0 = Monday … 6 = Sunday.
    op.create_table(
        "restaurant_working_hours",
        _id(),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=True),
        sa.Column("closes_at", sa.Time(), nullable=True),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_restaurant_working_hours_weekday_range")
        ),
        sa.CheckConstraint(
            "is_closed OR (opens_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND opens_at <> closes_at)",
            name=op.f("ck_restaurant_working_hours_open_day_interval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restaurant_working_hours")),
        sa.UniqueConstraint("weekday", name=op.f("uq_restaurant_working_hours_weekday")),
    )

    # §8.1 — payment method reference (`payments` itself comes in 0007).
    op.create_table(
        "payment_methods",
        _id(),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_methods")),
        sa.UniqueConstraint("code", name=op.f("uq_payment_methods_code")),
    )

    # §9.1 — delivery zones with a PostGIS MultiPolygon boundary in SRID 4326.
    op.create_table(
        "delivery_zones",
        _id(),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("delivery_fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "min_order_amount",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "boundary",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "delivery_fee >= 0", name=op.f("ck_delivery_zones_delivery_fee_non_negative")
        ),
        sa.CheckConstraint(
            "min_order_amount >= 0", name=op.f("ck_delivery_zones_min_order_amount_non_negative")
        ),
        sa.CheckConstraint(
            "NOT is_active OR boundary IS NOT NULL",
            name=op.f("ck_delivery_zones_active_requires_boundary"),
        ),
        # DEC-122: NULL allowed, a present geometry must be valid.
        sa.CheckConstraint(
            "boundary IS NULL OR ST_IsValid(boundary)",
            name=op.f("ck_delivery_zones_boundary_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_zones")),
    )
    op.create_index(
        "ix_delivery_zones_boundary", "delivery_zones", ["boundary"], postgresql_using="gist"
    )


def downgrade() -> None:
    # Reverse order; indexes are dropped together with their tables.
    op.drop_table("delivery_zones")
    op.drop_table("payment_methods")
    op.drop_table("restaurant_working_hours")
    op.drop_table("restaurant_settings")
