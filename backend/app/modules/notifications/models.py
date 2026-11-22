"""Notifications and Telegram tables (DATABASE_SCHEMA.md §11; DEC-116).

Structure only. In v1 notifications are for customers only (DEC-57,
DEC-85); the text is built on the frontend from `type` + `payload`
(DEC-55). Rules that constraints cannot express live in the service layer
and the worker: payload shape per type, read marking, link-token issue and
one-time use (DEC-87), chat ownership, outbox creation in the same
transaction as the order change (DEC-75), language fixed at event creation
and the retry policy (DEC-104, DEC-105).
Relationships use `lazy="raise"`: load them explicitly (DEC-121).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import Language, sql_in
from app.modules.notifications.enums import NotificationType, TelegramOutboxStatus
from app.modules.orders.models import Order
from app.modules.users.models import User


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="notifications", lazy="raise")
    order: Mapped[Order | None] = relationship(back_populates="notifications", lazy="raise")

    __table_args__ = (
        Index(
            "ix_notifications_user_id_is_read_created_at",
            "user_id",
            "is_read",
            text("created_at DESC"),
        ),
        Index("ix_notifications_order_id", "order_id"),  # DEC-135
        CheckConstraint(sql_in("type", NotificationType), name="type"),  # DEC-126
    )


class TelegramLink(UUIDPrimaryKeyMixin, Base):
    """One link per user and per chat; unlinking deletes the row (§11.2)."""

    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(100))
    # Permission for the bot to write to the user, not a sign of the link (a
    # link exists iff the row exists; DEC-152 п. 8, DEC-154 п. 3): set from the
    # verified allows_write_to_pm when the link is created; raised to TRUE by a
    # later login/relink with allows_write_to_pm=true, never lowered by them;
    # FALSE after Telegram answered 403 (stage 10).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # No default: the service sets it explicitly.
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="telegram_link", lazy="raise")


class TelegramLinkToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One-time link token; only its SHA-256 hash is stored (DEC-87, DEC-105)."""

    __tablename__ = "telegram_link_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # created_at + TTL from configuration, set by the service.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="telegram_link_tokens", lazy="raise")

    __table_args__ = (
        Index("ix_telegram_link_tokens_user_id", "user_id"),  # DEC-135
    )


class TelegramOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Transactional outbox of Telegram messages (DEC-75, §11.4)."""

    __tablename__ = "telegram_outbox"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # No default (§11.4); never contains address, phone, amounts or tokens.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # users.preferred_language at event creation (DEC-105).
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=TelegramOutboxStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="telegram_outbox", lazy="raise")
    order: Mapped[Order | None] = relationship(back_populates="telegram_outbox", lazy="raise")

    __table_args__ = (
        Index("ix_telegram_outbox_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_telegram_outbox_user_id", "user_id"),  # DEC-135
        Index("ix_telegram_outbox_order_id", "order_id"),  # DEC-135
        CheckConstraint(sql_in("event_type", NotificationType), name="event_type"),  # DEC-126
        CheckConstraint(sql_in("language_code", Language), name="language_code"),
        CheckConstraint(sql_in("status", TelegramOutboxStatus), name="status"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )
