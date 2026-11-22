"""Checkout and order requests/responses (API §6, DEC-86, DEC-148).

Money is `Decimal`, serialized as a decimal string ("450.00"). Prices,
fees and totals are never accepted from the client; `expected_total` is
only compared (DEC-09).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.core.language import LanguageCode
from app.core.phone import normalize_phone
from app.modules.addresses.schemas import DeliveryAddressIn, Latitude, Longitude, Pagination

# DEC-148
MAX_CUSTOMER_COMMENT = 500
MAX_CUSTOMER_NAME = 150
MAX_CANCELLATION_REASON = 500
CURRENCY = "KGS"

DeliveryTypeIn = Literal["delivery", "pickup"]


def _text(limit: int, *, required: bool):  # noqa: ANN202 - returns a validator
    def validate(value: str | None) -> str | None:
        if value is None:
            if required:
                raise ValueError("обязательное поле")
            return None
        cleaned = value.strip()
        if required and not cleaned:
            raise ValueError("обязательное поле")
        if len(cleaned) > limit:
            raise ValueError(f"не более {limit} символов")
        return cleaned or None

    return validate


def _phone(value: str) -> str:
    return normalize_phone(value)


def _money(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("не более 2 знаков после запятой")
    return value.quantize(Decimal("0.01"))


CustomerName = Annotated[
    str,
    Field(max_length=MAX_CUSTOMER_NAME * 2),
    AfterValidator(_text(MAX_CUSTOMER_NAME, required=True)),
]
CustomerComment = Annotated[
    str | None,
    Field(max_length=MAX_CUSTOMER_COMMENT * 2),
    AfterValidator(_text(MAX_CUSTOMER_COMMENT, required=False)),
]
CancellationReason = Annotated[
    str,
    Field(max_length=MAX_CANCELLATION_REASON * 2),
    AfterValidator(_text(MAX_CANCELLATION_REASON, required=True)),
]
Phone = Annotated[str, Field(max_length=40), AfterValidator(_phone)]
MoneyIn = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999.99")), AfterValidator(_money)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuotePoint(_In):
    """For a quote only the point matters; other address fields are ignored."""

    latitude: Latitude
    longitude: Longitude
    address_text: str | None = Field(default=None, max_length=1000)
    label: str | None = Field(default=None, max_length=200)
    entrance: str | None = Field(default=None, max_length=100)
    floor: str | None = Field(default=None, max_length=100)
    apartment: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)


def _check_destination(
    delivery_type: str, address_id: uuid.UUID | None, address: object | None, fields: set[str]
) -> None:
    if delivery_type == "delivery":
        if (address_id is None) == (address is None):
            raise ValueError("для доставки укажите ровно одно из address_id или address")
    elif address_id is not None or address is not None or "save_address" in fields:
        raise ValueError("для самовывоза адрес не передаётся")


class QuoteIn(_In):
    delivery_type: DeliveryTypeIn
    address_id: uuid.UUID | None = None
    address: QuotePoint | None = None

    @model_validator(mode="after")
    def _destination(self) -> Self:
        _check_destination(self.delivery_type, self.address_id, self.address, set())
        return self


class OrderCreate(_In):
    delivery_type: DeliveryTypeIn
    address_id: uuid.UUID | None = None
    address: DeliveryAddressIn | None = None
    save_address: bool = False
    customer_name: CustomerName
    customer_phone: Phone
    comment: CustomerComment = None
    payment_method_code: str = Field(min_length=1, max_length=30)
    expected_total: MoneyIn
    language: LanguageCode | None = None

    @model_validator(mode="after")
    def _destination(self) -> Self:
        _check_destination(
            self.delivery_type, self.address_id, self.address, set(self.model_fields_set)
        )
        if self.save_address and self.address is None:
            raise ValueError("save_address применим только к новому адресу (address)")
        return self

    def canonical(self) -> dict[str, Any]:
        """Normalized body for the idempotency hash (§14.2): every field
        present, missing optional values as null, money as 2-place strings,
        phone after normalization (DEC-148)."""
        address = None
        if self.address is not None:
            address = {
                "address_text": self.address.address_text,
                "apartment": self.address.apartment,
                "comment": self.address.comment,
                "entrance": self.address.entrance,
                "floor": self.address.floor,
                "label": self.address.label,
                "latitude": f"{self.address.latitude:.7f}",
                "longitude": f"{self.address.longitude:.7f}",
            }
        return {
            "address": address,
            "address_id": str(self.address_id) if self.address_id else None,
            "comment": self.comment,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "delivery_type": self.delivery_type,
            "expected_total": f"{self.expected_total:.2f}",
            "language": self.language,
            "payment_method_code": self.payment_method_code,
            "save_address": self.save_address,
        }


class CancellationRequestCreate(_In):
    reason: CancellationReason


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------


class ProblemOut(BaseModel):
    """A reason why the order cannot be placed now (codes of API §1.1)."""

    code: str
    details: Any = None


class ZoneOut(BaseModel):
    id: uuid.UUID
    name: str


class QuoteOut(BaseModel):
    delivery_type: str
    items_count: int
    # Sum of the available lines (DEC-147).
    subtotal: Decimal
    zone: ZoneOut | None
    delivery_fee: Decimal
    # Minimum that applies to this order type and zone (DEC-17, DEC-18).
    min_order_amount: Decimal
    min_order_reached: bool
    total: Decimal
    currency: str = CURRENCY
    is_open_now: bool
    next_opening_at: datetime | None
    delivery_enabled: bool
    pickup_enabled: bool
    problems: list[ProblemOut]
    can_place_order: bool


class OrderCreated(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    delivery_type: str
    payment_method_code: str
    payment_status: str
    payment_due_at: datetime | None
    subtotal: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
    currency: str
    created_at: datetime


class OrderSummary(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    delivery_type: str
    payment_method_code: str
    total_amount: Decimal
    currency: str
    items_count: int
    created_at: datetime


class OrderList(BaseModel):
    items: list[OrderSummary]
    pagination: Pagination


class OrderItemModifierOut(BaseModel):
    group_name: str
    modifier_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal


class OrderItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    product_name: str
    variant_name: str
    # Price of the size alone (DEC-61).
    unit_price: Decimal
    quantity: int
    total_price: Decimal
    special_instructions: str | None
    modifiers: list[OrderItemModifierOut]


class OrderAddressOut(BaseModel):
    address_text: str
    latitude: Decimal
    longitude: Decimal
    entrance: str | None
    floor: str | None
    apartment: str | None
    comment: str | None


class PaymentOut(BaseModel):
    # For mock_card this id is the `attempt_id` of the confirmation (DEC-149).
    id: uuid.UUID
    method_code: str
    amount: Decimal
    currency: str
    status: str
    is_simulated: bool
    # Simulated reference of a mock attempt (`MOCK-…`); NULL for cash.
    transaction_reference: str | None
    created_at: datetime
    paid_at: datetime | None
    refunded_at: datetime | None


class StatusHistoryOut(BaseModel):
    old_status: str | None
    new_status: str
    # Shown only for rejected/cancelled: the reason (DEC-98, DEC-132).
    comment: str | None
    created_at: datetime


class CancellationRequestOut(BaseModel):
    id: uuid.UUID
    reason: str
    status: str
    admin_comment: str | None
    created_at: datetime
    reviewed_at: datetime | None


class OrderDetail(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    language_code: str
    delivery_type: str
    payment_method_code: str
    payment_status: str | None
    subtotal: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
    currency: str
    customer_name: str
    customer_phone: str
    customer_comment: str | None
    address: OrderAddressOut | None
    payment_due_at: datetime | None
    cancellation_reason_code: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    items: list[OrderItemOut]
    payments: list[PaymentOut]
    status_history: list[StatusHistoryOut]
    cancellation_requests: list[CancellationRequestOut]
    can_request_cancellation: bool
