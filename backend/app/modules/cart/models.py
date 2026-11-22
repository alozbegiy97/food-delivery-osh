"""Server-side cart (DATABASE_SCHEMA.md §6).

Structure only. Prices are never stored in the cart: they are recalculated
by the backend on every read, quote and checkout (DEC-08). Rules that
constraints cannot express live in the service layer:
- only users with the `customer` role have a cart (DEC-13, DEC-23);
- `variant_id` belongs to `product_id` (§6.2);
- identical lines are merged; PATCH changes only quantity/instructions
  (DEC-11, DEC-12);
- modifier availability, `quantity <= modifiers.max_quantity` and group
  limits (§5.7, DEC-81).
Relationships use `lazy="raise"`: load them explicitly (DEC-121).
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Cart(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One active cart per user; the row is kept and reused after checkout."""

    __tablename__ = "carts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", lazy="raise", passive_deletes=True
    )


class CartItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cart_items"

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # Always set (DEC-06).
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(Text)

    cart: Mapped[Cart] = relationship(back_populates="items", lazy="raise")
    modifiers: Mapped[list["CartItemModifier"]] = relationship(
        back_populates="cart_item", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_cart_items_cart_id", "cart_id"),
        Index("ix_cart_items_product_id", "product_id"),  # DEC-130
        Index("ix_cart_items_variant_id", "variant_id"),  # DEC-130
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class CartItemModifier(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cart_item_modifiers"

    cart_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cart_items.id", ondelete="CASCADE"), nullable=False
    )
    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modifiers.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))

    cart_item: Mapped[CartItem] = relationship(back_populates="modifiers", lazy="raise")

    __table_args__ = (
        UniqueConstraint("cart_item_id", "modifier_id"),
        Index("ix_cart_item_modifiers_modifier_id", "modifier_id"),  # DEC-130
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )
