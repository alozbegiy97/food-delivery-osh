"""Payment methods and payment attempts (DATABASE_SCHEMA.md §8; DEC-116).

`payment_methods` belongs to revision 0003, `payments` to revision 0007.
Payment-method rows are inserted by the `base` seed.

Structure only. Rules that constraints cannot express live in the service
layer: `is_simulated = TRUE` for `mock_card`, `amount = orders.total_amount`,
the payment lifecycle and its timestamps (DEC-43…DEC-47, DEC-99, DEC-100)
and refund idempotency. At most one `succeeded` and one `pending` attempt
per order are enforced by partial unique indexes.
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
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import Money, sql_in
from app.modules.orders.enums import CURRENCY_KGS
from app.modules.orders.models import Order
from app.modules.payments.enums import PaymentStatus


class PaymentMethod(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "payment_methods"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    payment_method_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=CURRENCY_KGS)
    # No default: the service always sets the status explicitly (§8.2).
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_reference: Mapped[str | None] = mapped_column(String(120))
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="payments", lazy="raise")
    payment_method: Mapped[PaymentMethod] = relationship(lazy="raise")

    __table_args__ = (
        Index("ix_payments_order_id_created_at", "order_id", "created_at"),
        # At most one successful and one unfinished attempt per order (§8.2).
        Index(
            "uq_payments_order_id_succeeded",
            "order_id",
            unique=True,
            postgresql_where=text(f"status = '{PaymentStatus.SUCCEEDED}'"),
        ),
        Index(
            "uq_payments_order_id_pending",
            "order_id",
            unique=True,
            postgresql_where=text(f"status = '{PaymentStatus.PENDING}'"),
        ),
        Index("ix_payments_payment_method_id", "payment_method_id"),  # DEC-134
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(f"currency = '{CURRENCY_KGS}'", name="currency_kgs"),
        CheckConstraint(sql_in("status", PaymentStatus), name="status"),
    )
