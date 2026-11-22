"""Cart requests and responses (API_SPECIFICATION.md §5, DEC-07, DEC-12, DEC-146).

Money is `Decimal`, serialized as a decimal string ("450.00"). Prices are
never accepted from the client.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

# DEC-146
MAX_LINE_QUANTITY = 99
MAX_CART_LINES = 50
MAX_INSTRUCTIONS_LENGTH = 500
MAX_MODIFIERS_PER_LINE = 50
CURRENCY = "KGS"


def normalize_instructions(value: str | None) -> str | None:
    """Collapse whitespace (DEC-11 compares after normalization); empty -> None."""
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) > MAX_INSTRUCTIONS_LENGTH:
        raise ValueError(f"не более {MAX_INSTRUCTIONS_LENGTH} символов")
    return normalized or None


Instructions = Annotated[
    str | None,
    Field(max_length=MAX_INSTRUCTIONS_LENGTH * 4),
    AfterValidator(normalize_instructions),
]
LineQuantity = Annotated[int, Field(ge=1, le=MAX_LINE_QUANTITY)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModifierChoice(_In):
    id: uuid.UUID
    # Upper bound is the modifier's own `max_quantity` (checked by the service).
    quantity: Annotated[int, Field(ge=1, le=99)] = 1


class CartItemCreate(_In):
    product_id: uuid.UUID
    variant_id: uuid.UUID
    quantity: LineQuantity = 1
    modifiers: Annotated[list[ModifierChoice], Field(max_length=MAX_MODIFIERS_PER_LINE)] = []
    special_instructions: Instructions = None

    @model_validator(mode="after")
    def _unique_modifiers(self) -> Self:
        ids = [choice.id for choice in self.modifiers]
        if len(ids) != len(set(ids)):
            raise ValueError("каждая добавка указывается один раз")
        return self


class CartItemUpdate(_In):
    """DEC-12: only the quantity and the special instructions."""

    quantity: LineQuantity | None = None
    special_instructions: Instructions = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("укажите quantity или special_instructions")
        if "quantity" in self.model_fields_set and self.quantity is None:
            raise ValueError("quantity не может быть null")
        return self


class CartIssueOut(BaseModel):
    code: str
    group_id: uuid.UUID | None = None
    modifier_id: uuid.UUID | None = None
    group_name: str | None = None
    modifier_name: str | None = None
    limit: int | None = None


class CartModifierOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID | None
    group_name: str | None
    name: str
    quantity: int
    unit_price: Decimal


class CartItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    product_name: str
    variant_name: str
    image_url: str | None
    quantity: int
    special_instructions: str | None
    modifiers: list[CartModifierOut]
    # One unit (variant + extras) and the whole line; null only if the size
    # no longer exists for the product.
    unit_price: Decimal | None
    line_total: Decimal | None
    is_available: bool
    issues: list[CartIssueOut]


class CartOut(BaseModel):
    items: list[CartItemOut]
    # Sum of the line quantities (DEC-146).
    items_count: int
    # Sum of the lines without issues: only they can be ordered.
    subtotal: Decimal
    currency: str = CURRENCY
    has_issues: bool
    max_line_quantity: int = MAX_LINE_QUANTITY
    max_lines: int = MAX_CART_LINES
