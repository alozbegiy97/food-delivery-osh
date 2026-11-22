"""Catalog domain tables (DATABASE_SCHEMA.md §4, §5).

Structure only. Service-level invariants that constraints cannot express:
- every product has at least one variant (DEC-06);
- a modifier used for a variant belongs to a group linked to its product
  (§5.6);
- modifier selection rules at cart/quote/order time (§5.7, DEC-81).

Catalog rows are deactivated (`is_active`) or soft-deleted (`deleted_at`),
not physically deleted (DEC-26, §2.4).
Relationships use `lazy="raise"`: load them explicitly (DEC-121).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import Language, Money, sql_in
from app.modules.catalog.enums import SelectionType

LANGUAGE_CHECK = sql_in("language_code", Language)


def _fk(target: str, ondelete: str) -> ForeignKey:
    return ForeignKey(target, ondelete=ondelete)


# --------------------------------------------------------------------------- categories


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    image_path: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # "Deleting" a category means deactivating it (DEC-26).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    translations: Mapped[list["CategoryTranslation"]] = relationship(
        back_populates="category", lazy="raise", passive_deletes=True
    )
    products: Mapped[list["Product"]] = relationship(back_populates="category", lazy="raise")


class CategoryTranslation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "category_translations"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("categories.id", "CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    category: Mapped[Category] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("category_id", "language_code"),
        CheckConstraint(LANGUAGE_CHECK, name="language_code"),
    )


# --------------------------------------------------------------------------- products


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("categories.id", "RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Soft delete (DEC-26, §2.4); NULL = not deleted.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category: Mapped[Category] = relationship(back_populates="products", lazy="raise")
    translations: Mapped[list["ProductTranslation"]] = relationship(
        back_populates="product", lazy="raise", passive_deletes=True
    )
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", lazy="raise", passive_deletes=True
    )
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", lazy="raise", passive_deletes=True
    )
    modifier_group_links: Mapped[list["ProductModifierGroup"]] = relationship(
        back_populates="product", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        # Public catalog listing of non-deleted products (DEC-58, D6).
        Index(
            "ix_products_category_id_is_available_sort_order",
            "category_id",
            "is_available",
            "sort_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ProductTranslation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_translations"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("products.id", "CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("product_id", "language_code"),
        CheckConstraint(LANGUAGE_CHECK, name="language_code"),
    )


class ProductImage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("products.id", "CASCADE"), nullable=False
    )
    # Server-generated storage key, never the client's file name (DEC-70).
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    product: Mapped[Product] = relationship(back_populates="images", lazy="raise")

    __table_args__ = (
        Index("ix_product_images_product_id_sort_order", "product_id", "sort_order"),
        # At most one primary image per product.
        Index(
            "uq_product_images_product_id_primary",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("products.id", "CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    product: Mapped[Product] = relationship(back_populates="variants", lazy="raise")
    translations: Mapped[list["ProductVariantTranslation"]] = relationship(
        back_populates="variant", lazy="raise", passive_deletes=True
    )
    modifier_prices: Mapped[list["VariantModifierPrice"]] = relationship(
        back_populates="variant", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_product_variants_product_id", "product_id"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )


class ProductVariantTranslation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_variant_translations"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("product_variants.id", "CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    variant: Mapped[ProductVariant] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("variant_id", "language_code"),
        CheckConstraint(LANGUAGE_CHECK, name="language_code"),
    )


# --------------------------------------------------------------------------- modifiers


class ModifierGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "modifier_groups"

    selection_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Count distinct selected modifiers, not quantities (DEC-81).
    min_selections: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_selections: Mapped[int | None] = mapped_column(SmallInteger)  # NULL = no limit
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    translations: Mapped[list["ModifierGroupTranslation"]] = relationship(
        back_populates="group", lazy="raise", passive_deletes=True
    )
    modifiers: Mapped[list["Modifier"]] = relationship(
        back_populates="group", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(sql_in("selection_type", SelectionType), name="selection_type"),
        CheckConstraint("min_selections >= 0", name="min_selections_non_negative"),
        CheckConstraint("max_selections > 0", name="max_selections_positive"),
        # D1 (DEC-58).
        CheckConstraint(
            "max_selections IS NULL OR min_selections <= max_selections",
            name="min_not_greater_than_max",
        ),
        # D1 in strict form: NULL is rejected for single groups (DEC-128).
        CheckConstraint(
            "selection_type <> 'single' OR max_selections IS NOT DISTINCT FROM 1",
            name="single_max_one",
        ),
        CheckConstraint("is_required = (min_selections >= 1)", name="required_matches_min"),
    )


class ModifierGroupTranslation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "modifier_group_translations"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifier_groups.id", "CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    group: Mapped[ModifierGroup] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("group_id", "language_code"),
        CheckConstraint(LANGUAGE_CHECK, name="language_code"),
    )


class Modifier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "modifiers"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifier_groups.id", "CASCADE"), nullable=False
    )
    # Default surcharge for one unit of the modifier.
    price_delta: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default=text("0"))
    # Max quantity of this modifier in one cart/order line (DEC-81).
    max_quantity: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    group: Mapped[ModifierGroup] = relationship(back_populates="modifiers", lazy="raise")
    translations: Mapped[list["ModifierTranslation"]] = relationship(
        back_populates="modifier", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_modifiers_group_id", "group_id"),
        CheckConstraint("price_delta >= 0", name="price_delta_non_negative"),
        CheckConstraint("max_quantity > 0", name="max_quantity_positive"),
    )


class ModifierTranslation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "modifier_translations"

    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifiers.id", "CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    modifier: Mapped[Modifier] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("modifier_id", "language_code"),
        CheckConstraint(LANGUAGE_CHECK, name="language_code"),
    )


# --------------------------------------------------------------------------- links


class ProductModifierGroup(Base):
    """Modifier groups available to a product (§5.5)."""

    __tablename__ = "product_modifier_groups"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("products.id", "CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifier_groups.id", "RESTRICT"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    product: Mapped[Product] = relationship(back_populates="modifier_group_links", lazy="raise")
    group: Mapped[ModifierGroup] = relationship(lazy="raise")

    __table_args__ = (Index("ix_product_modifier_groups_group_id", "group_id"),)  # DEC-129


class VariantModifierPrice(Base):
    """Per-variant override of a modifier surcharge (§5.6)."""

    __tablename__ = "variant_modifier_prices"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("product_variants.id", "CASCADE"), primary_key=True
    )
    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifiers.id", "CASCADE"), primary_key=True
    )
    price_delta: Mapped[Decimal] = mapped_column(Money, nullable=False)

    variant: Mapped[ProductVariant] = relationship(back_populates="modifier_prices", lazy="raise")
    modifier: Mapped[Modifier] = relationship(lazy="raise")

    __table_args__ = (
        Index("ix_variant_modifier_prices_modifier_id", "modifier_id"),  # DEC-129
        CheckConstraint("price_delta >= 0", name="price_delta_non_negative"),
    )
