"""Cart domain tables (DATABASE_SCHEMA.md §6; DEC-116).

Tables: carts, cart_items, cart_item_modifiers. One cart per user
(UNIQUE user_id); prices are not stored (DEC-08). Foreign keys to the
catalog are RESTRICT; indexes on them follow DEC-130.

Revision ID: 0005_carts
Revises: 0004_catalog
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_carts"
down_revision: str | None = "0004_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
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
            ["user_id"], ["users.id"], name=op.f("fk_carts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carts")),
        sa.UniqueConstraint("user_id", name=op.f("uq_carts_user_id")),
    )
    op.create_table(
        "cart_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("special_instructions", sa.Text(), nullable=True),
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
        sa.CheckConstraint("quantity > 0", name=op.f("ck_cart_items_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_cart_items_cart_id_carts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_cart_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_cart_items_variant_id_product_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cart_items")),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"], unique=False)
    op.create_index("ix_cart_items_product_id", "cart_items", ["product_id"], unique=False)
    op.create_index("ix_cart_items_variant_id", "cart_items", ["variant_id"], unique=False)
    op.create_table(
        "cart_item_modifiers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cart_item_id", sa.UUID(), nullable=False),
        sa.Column("modifier_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_cart_item_modifiers_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["cart_item_id"],
            ["cart_items.id"],
            name=op.f("fk_cart_item_modifiers_cart_item_id_cart_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["modifier_id"],
            ["modifiers.id"],
            name=op.f("fk_cart_item_modifiers_modifier_id_modifiers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cart_item_modifiers")),
        sa.UniqueConstraint(
            "cart_item_id",
            "modifier_id",
            name=op.f("uq_cart_item_modifiers_cart_item_id_modifier_id"),
        ),
    )
    op.create_index(
        "ix_cart_item_modifiers_modifier_id", "cart_item_modifiers", ["modifier_id"], unique=False
    )


def downgrade() -> None:
    # Reverse dependency order; indexes are dropped together with their tables.
    op.drop_table("cart_item_modifiers")
    op.drop_table("cart_items")
    op.drop_table("carts")
