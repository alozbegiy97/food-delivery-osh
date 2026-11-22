"""Payments and deliveries domain tables (DATABASE_SCHEMA.md §8.2, §9.2, §9.3; DEC-116).

Creates payments, deliveries and courier_assignments. Constraints follow
the schema document; DEC-134 adds indexes on payments.payment_method_id,
deliveries.delivery_zone_id and courier_assignments.assigned_by.
Lifecycle and assignment rules are enforced by the service layer.

Revision ID: 0007_payments_deliveries
Revises: 0006_orders
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_payments_deliveries"
down_revision: str | None = "0006_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("payment_method_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="KGS", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("transaction_reference", sa.String(length=120), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency = 'KGS'", name=op.f("ck_payments_currency_kgs")),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded', 'cancelled')",
            name=op.f("ck_payments_status"),
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_payments_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_methods.id"],
            name=op.f("fk_payments_payment_method_id_payment_methods"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
    )
    op.create_index(
        "ix_payments_order_id_created_at", "payments", ["order_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_payments_payment_method_id", "payments", ["payment_method_id"], unique=False
    )
    op.create_index(
        "uq_payments_order_id_pending",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_payments_order_id_succeeded",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("delivery_zone_id", sa.UUID(), nullable=True),
        sa.Column("delivery_comment", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["delivery_zone_id"],
            ["delivery_zones.id"],
            name=op.f("fk_deliveries_delivery_zone_id_delivery_zones"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_deliveries_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deliveries")),
        sa.UniqueConstraint("order_id", name=op.f("uq_deliveries_order_id")),
    )
    op.create_index(
        "ix_deliveries_delivery_zone_id", "deliveries", ["delivery_zone_id"], unique=False
    )
    op.create_table(
        "courier_assignments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("courier_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        sa.Column("assignment_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'declined') = (declined_at IS NOT NULL)",
            name=op.f("ck_courier_assignments_declined_at_matches_status"),
        ),
        sa.CheckConstraint(
            "assignment_type IN ('manual', 'automatic')",
            name=op.f("ck_courier_assignments_assignment_type"),
        ),
        sa.CheckConstraint(
            "status <> 'declined' OR accepted_at IS NULL",
            name=op.f("ck_courier_assignments_declined_not_accepted"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled', 'declined')",
            name=op.f("ck_courier_assignments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_courier_assignments_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["courier_id"],
            ["users.id"],
            name=op.f("fk_courier_assignments_courier_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_courier_assignments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courier_assignments")),
    )
    op.create_index(
        "ix_courier_assignments_assigned_by", "courier_assignments", ["assigned_by"], unique=False
    )
    op.create_index(
        "ix_courier_assignments_courier_id_status",
        "courier_assignments",
        ["courier_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_courier_assignments_order_id_courier_id",
        "courier_assignments",
        ["order_id", "courier_id"],
        unique=False,
    )
    op.create_index(
        "uq_courier_assignments_order_id_active",
        "courier_assignments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("courier_assignments")
    op.drop_table("deliveries")
    op.drop_table("payments")
