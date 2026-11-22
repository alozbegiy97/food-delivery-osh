"""Courier and assignment schemas (API §9 "Couriers", §10; DATABASE_SCHEMA.md
§3.4, §9.3; DEC-106, DEC-151).

The courier sees the data needed for the delivery of his active assignments
only (DEC-106): address from the snapshot, name, phone, comments, items,
payment method and the amount. History rows hide the address and contacts.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.modules.addresses.schemas import Pagination

MAX_DECLINE_REASON = 500
MIN_ACTIVE_ORDERS = 1
MAX_ACTIVE_ORDERS = 10  # DEC-151 п. 2


def _reason(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > MAX_DECLINE_REASON:
        raise ValueError(f"не более {MAX_DECLINE_REASON} символов")
    return cleaned or None


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


class AssignCourierIn(_In):
    courier_id: uuid.UUID


class CourierSettingsIn(_In):
    """Administrator: availability and the limit (DEC-151 п. 2)."""

    is_available: bool | None = None
    max_active_orders: Annotated[int | None, Field(ge=MIN_ACTIVE_ORDERS, le=MAX_ACTIVE_ORDERS)] = (
        None
    )

    @model_validator(mode="after")
    def _one_field(self) -> Self:
        if self.is_available is None and self.max_active_orders is None:
            raise ValueError("укажите is_available или max_active_orders")
        return self


class AvailabilityIn(_In):
    """Courier: only his availability (DEC-151 п. 2)."""

    is_available: bool


class DeclineIn(_In):
    reason: Annotated[
        str | None, Field(max_length=MAX_DECLINE_REASON * 2), AfterValidator(_reason)
    ] = None


# --------------------------------------------------------------------------
# Administrator views
# --------------------------------------------------------------------------


class CourierOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    is_active: bool
    is_available: bool
    max_active_orders: int
    active_assignments: int


class CourierList(BaseModel):
    items: list[CourierOut]


class AssignmentOut(BaseModel):
    """One assignment of an order, for the administrator (§9.3)."""

    id: uuid.UUID
    courier_id: uuid.UUID
    courier_name: str
    courier_phone: str | None
    assignment_type: str
    status: str
    assigned_by_name: str | None
    assigned_at: datetime
    accepted_at: datetime | None
    declined_at: datetime | None
    decline_reason: str | None
    completed_at: datetime | None


# --------------------------------------------------------------------------
# Courier views
# --------------------------------------------------------------------------


class CourierMe(BaseModel):
    user_id: uuid.UUID
    full_name: str
    is_available: bool
    max_active_orders: int
    active_assignments: int


class CourierItemModifier(BaseModel):
    group_name: str
    modifier_name: str
    quantity: int


class CourierItem(BaseModel):
    product_name: str
    variant_name: str
    quantity: int
    special_instructions: str | None
    modifiers: list[CourierItemModifier]


class CourierAddress(BaseModel):
    address_text: str
    latitude: Decimal
    longitude: Decimal
    entrance: str | None
    floor: str | None
    apartment: str | None
    # Comment for the courier (snapshot of the address comment, §9.2).
    comment: str | None


class CourierOrderOut(BaseModel):
    """An active assignment with the data of the delivery (DEC-106)."""

    assignment_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    status: str
    created_at: datetime
    assigned_at: datetime
    accepted_at: datetime | None
    address: CourierAddress | None
    customer_name: str
    customer_phone: str
    customer_comment: str | None
    items: list[CourierItem]
    payment_method_code: str
    total_amount: Decimal
    currency: str
    # Cash: the amount to collect; mock_card: already paid (None).
    amount_to_collect: Decimal | None
    can_accept: bool
    can_decline: bool
    can_pick_up: bool
    can_deliver: bool


class CourierActiveList(BaseModel):
    kind: Literal["active"] = "active"
    items: list[CourierOrderOut]


class CourierHistoryOut(BaseModel):
    """A completed or declined assignment: no address or contacts (DEC-106)."""

    assignment_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    assignment_status: str
    # completed_at for `completed`, declined_at for `declined`.
    finished_at: datetime | None
    total_amount: Decimal
    currency: str
    payment_method_code: str


class CourierHistoryList(BaseModel):
    kind: Literal["history"] = "history"
    items: list[CourierHistoryOut]
    pagination: Pagination
