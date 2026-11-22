"""Administrator order views and actions (API §9; DEC-82, DEC-91, DEC-97,
DEC-101, DEC-132, DEC-150)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.modules.addresses.schemas import Pagination
from app.modules.courier.schemas import AssignmentOut
from app.modules.orders.schemas import OrderDetail

MAX_COMMENT = 500


def _comment(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > MAX_COMMENT:
        raise ValueError(f"не более {MAX_COMMENT} символов")
    return cleaned or None


Comment = Annotated[str | None, Field(max_length=MAX_COMMENT * 2), AfterValidator(_comment)]


def _required_comment(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("обязательное поле")
    if len(cleaned) > MAX_COMMENT:
        raise ValueError(f"не более {MAX_COMMENT} символов")
    return cleaned


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "confirmed",
        "preparing",
        "ready_for_pickup",
        "out_for_delivery",
        "completed",
        "rejected",
        "cancelled",
    ]
    # Required for rejected/cancelled (DEC-132) and for the override of a
    # courier transition (DEC-91); checked by the state machine.
    comment: Comment = None


class RequestRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_comment: Annotated[
        str, Field(max_length=MAX_COMMENT * 2), AfterValidator(_required_comment)
    ]


class AdminOrderSummary(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    delivery_type: str
    payment_method_code: str
    payment_status: str | None
    # Unpaid mock_card order within its deadline: no actions (DEC-97).
    awaiting_payment: bool
    total_amount: Decimal
    currency: str
    customer_name: str
    customer_phone: str
    items_count: int
    has_pending_cancellation: bool
    # Delivery order in confirmed…ready_for_pickup without an active
    # assignment, e.g. after a decline (DEC-92, UI §4).
    needs_courier: bool
    # Courier of the active assignment, if any.
    courier_name: str | None
    created_at: datetime


class AdminOrderList(BaseModel):
    items: list[AdminOrderSummary]
    pagination: Pagination


class AdminHistoryOut(BaseModel):
    old_status: str | None
    new_status: str
    comment: str | None
    is_admin_override: bool
    changed_by_name: str | None
    created_at: datetime


class AdminOrderDetail(OrderDetail):
    customer_email: str | None
    awaiting_payment: bool
    delivery_zone_name: str | None
    admin_history: list[AdminHistoryOut]
    # Statuses the administrator may set now; for a delivery
    # `out_for_delivery` / `completed` are the override of DEC-91.
    allowed_statuses: list[str]
    # Courier assignments, oldest first (§9.3, DEC-151).
    assignments: list[AssignmentOut]
    needs_courier: bool
    # Assignment possible now (DEC-48): delivery in confirmed…ready_for_pickup.
    can_assign_courier: bool
    delivered_at: datetime | None


class AdminRequestOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    order_status: str
    customer_name: str
    reason: str
    status: str
    admin_comment: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by_name: str | None


class AdminRequestList(BaseModel):
    items: list[AdminRequestOut]
    pagination: Pagination


RequestStatusFilter = Literal["pending", "approved", "rejected", "all"]
