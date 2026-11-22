"""Catalog domain tables (DATABASE_SCHEMA.md §4, §5; DEC-116).

Tables: categories, category_translations, products, product_translations,
product_images, product_variants, product_variant_translations,
modifier_groups, modifier_group_translations, modifiers,
modifier_translations, product_modifier_groups, variant_modifier_prices.

Constraints follow §4–§5, D1/D6 (DEC-58) with the strict `single` CHECK
(DEC-128) and the foreign-key indexes of DEC-129. Structure only: catalog
rows come from the `demo` seed (DEC-117, DEC-120).

Revision ID: 0004_catalog
Revises: 0003_restaurant_delivery
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_catalog"
down_revision: str | None = "0003_restaurant_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_table(
        "modifier_groups",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("selection_type", sa.String(length=20), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("min_selections", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_selections", sa.SmallInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.CheckConstraint(
            "selection_type <> 'single' OR max_selections IS NOT DISTINCT FROM 1",
            name=op.f("ck_modifier_groups_single_max_one"),
        ),
        sa.CheckConstraint(
            "selection_type IN ('single', 'multiple')",
            name=op.f("ck_modifier_groups_selection_type"),
        ),
        sa.CheckConstraint(
            "is_required = (min_selections >= 1)",
            name=op.f("ck_modifier_groups_required_matches_min"),
        ),
        sa.CheckConstraint(
            "max_selections > 0", name=op.f("ck_modifier_groups_max_selections_positive")
        ),
        sa.CheckConstraint(
            "max_selections IS NULL OR min_selections <= max_selections",
            name=op.f("ck_modifier_groups_min_not_greater_than_max"),
        ),
        sa.CheckConstraint(
            "min_selections >= 0", name=op.f("ck_modifier_groups_min_selections_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_groups")),
    )
    op.create_table(
        "category_translations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "language_code IN ('ru', 'ky', 'uz')",
            name=op.f("ck_category_translations_language_code"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_category_translations_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_translations")),
        sa.UniqueConstraint(
            "category_id",
            "language_code",
            name=op.f("uq_category_translations_category_id_language_code"),
        ),
    )
    op.create_table(
        "modifier_group_translations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "language_code IN ('ru', 'ky', 'uz')",
            name=op.f("ck_modifier_group_translations_language_code"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["modifier_groups.id"],
            name=op.f("fk_modifier_group_translations_group_id_modifier_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_group_translations")),
        sa.UniqueConstraint(
            "group_id",
            "language_code",
            name=op.f("uq_modifier_group_translations_group_id_language_code"),
        ),
    )
    op.create_table(
        "modifiers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column(
            "price_delta",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("max_quantity", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.CheckConstraint("max_quantity > 0", name=op.f("ck_modifiers_max_quantity_positive")),
        sa.CheckConstraint("price_delta >= 0", name=op.f("ck_modifiers_price_delta_non_negative")),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["modifier_groups.id"],
            name=op.f("fk_modifiers_group_id_modifier_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifiers")),
    )
    op.create_index("ix_modifiers_group_id", "modifiers", ["group_id"], unique=False)
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("slug", name=op.f("uq_products_slug")),
    )
    op.create_index(
        "ix_products_category_id_is_available_sort_order",
        "products",
        ["category_id", "is_available", "sort_order"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "modifier_translations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("modifier_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "language_code IN ('ru', 'ky', 'uz')",
            name=op.f("ck_modifier_translations_language_code"),
        ),
        sa.ForeignKeyConstraint(
            ["modifier_id"],
            ["modifiers.id"],
            name=op.f("fk_modifier_translations_modifier_id_modifiers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_translations")),
        sa.UniqueConstraint(
            "modifier_id",
            "language_code",
            name=op.f("uq_modifier_translations_modifier_id_language_code"),
        ),
    )
    op.create_table(
        "product_images",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_images_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_images")),
    )
    op.create_index(
        "ix_product_images_product_id_sort_order",
        "product_images",
        ["product_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_product_images_product_id_primary",
        "product_images",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "product_modifier_groups",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["modifier_groups.id"],
            name=op.f("fk_product_modifier_groups_group_id_modifier_groups"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_modifier_groups_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("product_id", "group_id", name=op.f("pk_product_modifier_groups")),
    )
    op.create_index(
        "ix_product_modifier_groups_group_id", "product_modifier_groups", ["group_id"], unique=False
    )
    op.create_table(
        "product_translations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "language_code IN ('ru', 'ky', 'uz')",
            name=op.f("ck_product_translations_language_code"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_translations_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_translations")),
        sa.UniqueConstraint(
            "product_id",
            "language_code",
            name=op.f("uq_product_translations_product_id_language_code"),
        ),
    )
    op.create_table(
        "product_variants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.CheckConstraint("price >= 0", name=op.f("ck_product_variants_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_variants_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
        sa.UniqueConstraint("sku", name=op.f("uq_product_variants_sku")),
    )
    op.create_index(
        "ix_product_variants_product_id", "product_variants", ["product_id"], unique=False
    )
    op.create_table(
        "product_variant_translations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "language_code IN ('ru', 'ky', 'uz')",
            name=op.f("ck_product_variant_translations_language_code"),
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_product_variant_translations_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variant_translations")),
        sa.UniqueConstraint(
            "variant_id",
            "language_code",
            name=op.f("uq_product_variant_translations_variant_id_language_code"),
        ),
    )
    op.create_table(
        "variant_modifier_prices",
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("modifier_id", sa.UUID(), nullable=False),
        sa.Column("price_delta", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint(
            "price_delta >= 0", name=op.f("ck_variant_modifier_prices_price_delta_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["modifier_id"],
            ["modifiers.id"],
            name=op.f("fk_variant_modifier_prices_modifier_id_modifiers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_variant_modifier_prices_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "variant_id", "modifier_id", name=op.f("pk_variant_modifier_prices")
        ),
    )
    op.create_index(
        "ix_variant_modifier_prices_modifier_id",
        "variant_modifier_prices",
        ["modifier_id"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse dependency order; indexes are dropped together with their tables.
    op.drop_table("variant_modifier_prices")
    op.drop_table("product_variant_translations")
    op.drop_table("product_variants")
    op.drop_table("product_translations")
    op.drop_table("product_modifier_groups")
    op.drop_table("product_images")
    op.drop_table("modifier_translations")
    op.drop_table("products")
    op.drop_table("modifiers")
    op.drop_table("modifier_group_translations")
    op.drop_table("category_translations")
    op.drop_table("modifier_groups")
    op.drop_table("categories")
