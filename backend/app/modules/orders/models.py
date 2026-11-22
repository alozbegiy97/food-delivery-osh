"""Orders domain tables (DATABASE_SCHEMA.md §7, §14.2; DEC-116).

Structure only. An order keeps immutable snapshots of the customer, the
address, the delivery fee, item names and prices (DEC-15, DEC-16, DEC-60);
catalog foreign keys are SET NULL so history survives catalog changes.
Rules that constraints cannot express live in the service layer: status
transitions (§7.1), price formulas (DEC-61), cancellation (§14.3) and the
idempotency algorithm (DEC-109).
Relationships use `lazy="raise"`: load them explicitly (DEC-121).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import PHONE_PATTERN, Coordinate, Language, Money, sql_in
from app.modules.orders.enums import (
    CURRENCY_KGS,
    STATUSES_REQUIRING_COMMENT,
    CancellationReasonCode,
    CancellationRequestStatus,
    DeliveryType,
    OrderStatus,
)
from app.modules.users.models import User

if TYPE_CHECKING:
    # Declared in revision 0007/0008 modules, which import this module.
    from app.modules.delivery.models import CourierAssignment, Delivery
    from app.modules.notifications.models import Notification, TelegramOutbox
    from app.modules.payments.models import Payment

# SQL function created by revision 0006 (DEC-123): one nextval() per call,
# zero-padded to at least 6 digits and never truncated.
ORDER_NUMBER_DEFAULT = text("next_order_number()")
NON_EMPTY_COMMENT = "comment IS NOT NULL AND length(trim(comment)) > 0"
STATUS_LIST = ", ".join(f"'{status}'" for status in OrderStatus)


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    order_number: Mapped[str] = mapped_column(
        String(40), nullable=False, unique=True, server_default=ORDER_NUMBER_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Language of checkout and of the name snapshots (DEC-15).
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    delivery_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=OrderStatus.PENDING.value
    )
    # Snapshot of the chosen method (no FK by design).
    payment_method_code: Mapped[str] = mapped_column(String(30), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default=text("0"))
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=CURRENCY_KGS)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    # Address snapshot, only for delivery (DEC-16).
    delivery_address_text: Mapped[str | None] = mapped_column(Text)
    delivery_latitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    delivery_longitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    delivery_entrance: Mapped[str | None] = mapped_column(String(30))
    delivery_floor: Mapped[str | None] = mapped_column(String(20))
    delivery_apartment: Mapped[str | None] = mapped_column(String(30))
    customer_comment: Mapped[str | None] = mapped_column(Text)
    # mock_card payment deadline; NULL after payment and for cash (DEC-84, DEC-97).
    payment_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason_code: Mapped[str | None] = mapped_column(String(30))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="raise")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )
    cancellation_requests: Mapped[list["CancellationRequest"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )
    # Revision 0007 (DEC-116). ON DELETE RESTRICT: an order with payments,
    # a delivery or assignments cannot be deleted.
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes="all"
    )
    delivery: Mapped["Delivery | None"] = relationship(
        back_populates="order", lazy="raise", uselist=False, passive_deletes="all"
    )
    courier_assignments: Mapped[list["CourierAssignment"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes="all"
    )
    # Revision 0008 (DEC-116); ON DELETE SET NULL is done by the database.
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )
    telegram_outbox: Mapped[list["TelegramOutbox"]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_orders_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_orders_status_created_at", "status", "created_at"),
        # Background job: expired mock_card payments (DEC-84).
        Index(
            "ix_orders_payment_due_at_pending",
            "payment_due_at",
            postgresql_where=text("status = 'pending' AND payment_due_at IS NOT NULL"),
        ),
        CheckConstraint(sql_in("language_code", Language), name="language_code"),
        CheckConstraint(sql_in("delivery_type", DeliveryType), name="delivery_type"),
        CheckConstraint(sql_in("status", OrderStatus), name="status"),
        CheckConstraint(f"currency = '{CURRENCY_KGS}'", name="currency_kgs"),
        CheckConstraint(f"customer_phone ~ '{PHONE_PATTERN}'", name="customer_phone_format"),
        CheckConstraint("subtotal >= 0", name="subtotal_non_negative"),
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_non_negative"),
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint("total_amount = subtotal + delivery_fee", name="total_is_sum"),
        CheckConstraint(
            "cancellation_reason_code IS NULL OR "
            + sql_in("cancellation_reason_code", CancellationReasonCode),
            name="cancellation_reason_code",
        ),
        CheckConstraint(
            "delivery_type <> 'pickup' OR (delivery_address_text IS NULL "
            "AND delivery_latitude IS NULL AND delivery_longitude IS NULL "
            "AND delivery_entrance IS NULL AND delivery_floor IS NULL "
            "AND delivery_apartment IS NULL AND delivery_fee = 0)",
            name="pickup_without_delivery_fields",
        ),
        CheckConstraint(
            "delivery_type <> 'delivery' OR (delivery_address_text IS NOT NULL "
            "AND delivery_latitude IS NOT NULL AND delivery_longitude IS NOT NULL)",
            name="delivery_requires_address",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancellation_reason_code IS NOT NULL)",
            name="cancelled_has_reason",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="cancelled_has_timestamp",
        ),
    )


class OrderItem(UUIDPrimaryKeyMixin, Base):
    """Line snapshot in `orders.language_code` (DEC-15)."""

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL")
    )
    # Always set at checkout; NULL only after the variant is deleted.
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    product_name: Mapped[str] = mapped_column(String(180), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    # Variant price per unit, without modifiers.
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # (unit_price + Σ modifier.unit_price × modifier.quantity) × quantity (DEC-61).
    total_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
    modifiers: Mapped[list["OrderItemModifier"]] = relationship(
        back_populates="order_item", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_product_id", "product_id"),  # DEC-133
        Index("ix_order_items_variant_id", "variant_id"),  # DEC-133
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("total_price >= 0", name="total_price_non_negative"),
    )


class OrderItemModifier(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_item_modifiers"

    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    modifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modifiers.id", ondelete="SET NULL")
    )
    group_name: Mapped[str] = mapped_column(String(120), nullable=False)  # DEC-60
    modifier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Surcharge per unit, including the per-variant override.
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # unit_price × quantity for ONE unit of the order line.
    total_price: Mapped[Decimal] = mapped_column(Money, nullable=False)

    order_item: Mapped[OrderItem] = relationship(back_populates="modifiers", lazy="raise")

    __table_args__ = (
        Index("ix_order_item_modifiers_order_item_id", "order_item_id"),  # DEC-133
        Index("ix_order_item_modifiers_modifier_id", "modifier_id"),  # DEC-133
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("total_price >= 0", name="total_price_non_negative"),
    )


class OrderStatusHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "order_status_history"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    old_status: Mapped[str | None] = mapped_column(String(30))  # NULL for the first record
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    # NULL for system transitions; SET NULL interplay with the CHECK below (DEC-131).
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    # Admin performed a courier transition (DEC-91).
    is_admin_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    order: Mapped[Order] = relationship(back_populates="status_history", lazy="raise")

    __table_args__ = (
        Index("ix_order_status_history_order_id_created_at", "order_id", "created_at"),
        Index("ix_order_status_history_changed_by", "changed_by"),  # DEC-133
        CheckConstraint(f"old_status IS NULL OR old_status IN ({STATUS_LIST})", name="old_status"),
        CheckConstraint(f"new_status IN ({STATUS_LIST})", name="new_status"),
        # DATABASE_SCHEMA.md §7.5, DEC-131.
        CheckConstraint(
            f"NOT is_admin_override OR (changed_by IS NOT NULL AND {NON_EMPTY_COMMENT})",
            name="admin_override_author_comment",
        ),
        # DEC-132.
        CheckConstraint(
            "new_status NOT IN ("
            + ", ".join(f"'{status}'" for status in STATUSES_REQUIRING_COMMENT)
            + f") OR ({NON_EMPTY_COMMENT})",
            name="rejected_cancelled_require_comment",
        ),
    )


class CancellationRequest(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cancellation_requests"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=CancellationRequestStatus.PENDING.value
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    admin_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="cancellation_requests", lazy="raise")

    __table_args__ = (
        # At most one pending request per order (§7.6).
        Index(
            "uq_cancellation_requests_order_id_pending",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_cancellation_requests_order_id", "order_id"),  # DEC-133
        Index("ix_cancellation_requests_user_id", "user_id"),  # DEC-133
        Index("ix_cancellation_requests_reviewed_by", "reviewed_by"),  # DEC-133
        CheckConstraint(sql_in("status", CancellationRequestStatus), name="status"),
    )


class IdempotencyKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Idempotent order creation (§14.2, DEC-59, DEC-109)."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 of the canonical request body.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL while the original request is still in progress.
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    # Python None is stored as SQL NULL, not JSON 'null' (§14.2: JSONB NULL).
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # created_at + 24 h, set by the service (DEC-59).
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "scope", "key"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )
