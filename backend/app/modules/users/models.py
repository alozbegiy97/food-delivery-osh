"""Users domain tables (DATABASE_SCHEMA.md §3).

Models hold structure only. Business rules (email normalization, password
policy, phone normalization, role checks) live in the service layer.
Relationships use `lazy="raise"`: load them explicitly with
`selectinload` / `joinedload` (DEC-121).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import PHONE_PATTERN, Coordinate, Language, sql_in

if TYPE_CHECKING:
    # Declared in revision 0008 module, which imports this module.
    from app.modules.notifications.models import (
        Notification,
        TelegramLink,
        TelegramLinkToken,
        TelegramOutbox,
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # NULL together only for a Telegram-only account (DEC-142 K2-B, revision 0009).
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    preferred_language: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default=Language.RU.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Not used in v1 (DEC-64).
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    roles: Mapped[list["Role"]] = relationship(secondary="user_roles", lazy="raise")
    courier_profile: Mapped["CourierProfile | None"] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    addresses: Mapped[list["Address"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    # Revision 0008 (DEC-116); ON DELETE CASCADE is done by the database.
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    telegram_link: Mapped["TelegramLink | None"] = relationship(
        back_populates="user", lazy="raise", uselist=False, passive_deletes=True
    )
    telegram_link_tokens: Mapped[list["TelegramLinkToken"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    telegram_outbox: Mapped[list["TelegramOutbox"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        # Case-insensitive unique email (DATABASE_SCHEMA.md §3.1).
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        CheckConstraint(f"phone IS NULL OR phone ~ '{PHONE_PATTERN}'", name="phone_format"),
        CheckConstraint(sql_in("preferred_language", Language), name="preferred_language"),
        # Email and password are set together or both NULL (DEC-142).
        CheckConstraint("(email IS NULL) = (password_hash IS NULL)", name="credentials_pair"),
    )


class Role(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CourierProfile(TimestampMixin, Base):
    __tablename__ = "courier_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_active_orders: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )

    user: Mapped[User] = relationship(back_populates="courier_profile", lazy="raise")

    __table_args__ = (CheckConstraint("max_active_orders > 0", name="max_active_orders_positive"),)


class Address(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "addresses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(80))
    address_text: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    longitude: Mapped[Decimal | None] = mapped_column(Coordinate)
    entrance: Mapped[str | None] = mapped_column(String(30))
    floor: Mapped[str | None] = mapped_column(String(20))
    apartment: Mapped[str | None] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    user: Mapped[User] = relationship(back_populates="addresses", lazy="raise")

    __table_args__ = (
        Index("ix_addresses_user_id", "user_id"),
        # At most one default address per user (DATABASE_SCHEMA.md §3.5).
        Index(
            "uq_addresses_user_id_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )


class RefreshToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Shared by every token of one rotation chain (DEC-65).
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Only the hash is stored, never the raw token.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),
        Index("ix_refresh_tokens_family_id", "family_id"),
    )


class PasswordResetToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Only the hash is stored, never the raw token.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Find/invalidate a user's reset tokens (DEC-127).
        Index("ix_password_reset_tokens_user_id", "user_id"),
    )
